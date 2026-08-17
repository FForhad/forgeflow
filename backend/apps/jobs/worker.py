import logging
import signal
import socket
import sys
import time
import traceback
import uuid
from datetime import timedelta
from typing import List, Optional, Union

from django.utils import timezone
from apps.jobs.backoff import compute_backoff_delay
from apps.jobs.exceptions import is_retryable_exception
from apps.jobs.models import AttemptStatus, Job, JobAttempt, JobStatus
from apps.jobs.queue import RedisJobQueue, default_job_queue
from apps.jobs.tasks import get_task_handler

logger = logging.getLogger("forgeflow.worker")


class CustomWorker:
    """
    Independent Custom Async Worker for ForgeFlow with Retry & Exponential Backoff.
    Polls Redis queues via BRPOP, promotes due delayed retries from Redis ZSET,
    executes tasks, and records persistent attempts into PostgreSQL.
    """

    def __init__(
        self,
        queues: Optional[Union[str, List[str]]] = None,
        timeout: int = 2,
        worker_id: Optional[str] = None,
        queue_instance: Optional[RedisJobQueue] = None,
    ):
        if queues is None:
            self.queues = ["default"]
        elif isinstance(queues, str):
            self.queues = [q.strip() for q in queues.split(",") if q.strip()]
        else:
            self.queues = list(queues)

        self.timeout = timeout
        self.worker_id = worker_id or f"worker-{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        self.queue = queue_instance or default_job_queue
        self.is_running = False
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Sets up graceful shutdown signal traps for SIGINT and SIGTERM."""
        try:
            signal.signal(signal.SIGINT, self._handle_shutdown_signal)
            signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        except (ValueError, AttributeError):
            # Signal handlers can only be set from the main thread
            pass

    def _handle_shutdown_signal(self, signum, frame):
        sig_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        logger.info(f"[{self.worker_id}] Received {sig_name}. Initiating graceful shutdown...")
        self.stop()

    def stop(self):
        """Signals the worker loop to stop after finishing any in-flight job."""
        self.is_running = False

    def process_job(self, job_id: str, queue_name: str) -> bool:
        """
        Fetches job from PostgreSQL, updates state to RUNNING, executes the task,
        and saves execution result/failure into Job and JobAttempt tables.
        Handles retryable errors by computing exponential backoff and scheduling delayed retry.
        """
        logger.info(f"[{self.worker_id}] Processing job {job_id} from queue '{queue_name}'")

        try:
            job = Job.objects.prefetch_related('attempts').get(id=job_id)
        except (Job.DoesNotExist, ValueError) as exc:
            logger.warning(f"[{self.worker_id}] Job {job_id} not found in database: {exc}")
            return False

        # Check if job was already cancelled before worker picked it up
        if job.status == JobStatus.CANCELLED:
            logger.info(f"[{self.worker_id}] Job {job_id} is CANCELLED. Skipping execution.")
            return False

        # Determine attempt number
        attempt_number = job.attempts.count() + 1
        start_dt = timezone.now()

        attempt = JobAttempt.objects.create(
            job=job,
            attempt_number=attempt_number,
            worker_id=self.worker_id,
            status=AttemptStatus.RUNNING,
            started_at=start_dt,
        )

        job.status = JobStatus.RUNNING
        job.started_at = start_dt
        job.save(update_fields=['status', 'started_at'])

        # Execute registered task
        timer_start = time.monotonic()
        try:
            handler = get_task_handler(job.type)
            result = handler(job.payload)

            elapsed = time.monotonic() - timer_start
            duration = timedelta(seconds=elapsed)
            finish_dt = timezone.now()

            # Record success in attempt and job
            attempt.status = AttemptStatus.SUCCESS
            attempt.finished_at = finish_dt
            attempt.duration = duration
            attempt.save(update_fields=['status', 'finished_at', 'duration'])

            job.status = JobStatus.SUCCESS
            job.result = result
            job.error = None
            job.next_retry_at = None
            job.completed_at = finish_dt
            job.save(update_fields=['status', 'result', 'error', 'next_retry_at', 'completed_at'])

            logger.info(f"[{self.worker_id}] Job {job.id} ({job.type}) SUCCEEDED in {elapsed:.3f}s")
            return True

        except Exception as exc:
            elapsed = time.monotonic() - timer_start
            duration = timedelta(seconds=elapsed)
            finish_dt = timezone.now()
            error_traceback = traceback.format_exc()

            retryable = is_retryable_exception(exc)
            can_retry = retryable and (job.retry_count < job.max_retries)

            if can_retry:
                job.retry_count += 1
                delay = compute_backoff_delay(
                    attempt=job.retry_count,
                    base=job.backoff_base,
                    max_backoff=job.max_backoff,
                    use_jitter=job.use_jitter,
                )
                next_retry = finish_dt + timedelta(seconds=delay)

                # Record failed attempt
                attempt.status = AttemptStatus.FAILED
                attempt.finished_at = finish_dt
                attempt.duration = duration
                attempt.error = error_traceback
                attempt.save(update_fields=['status', 'finished_at', 'duration', 'error'])

                # Update job status to RETRYING and schedule next attempt
                job.status = JobStatus.RETRYING
                job.next_retry_at = next_retry
                job.error = str(exc)
                job.save(update_fields=['status', 'retry_count', 'next_retry_at', 'error'])

                # Schedule in Redis delayed ZSET
                self.queue.schedule_delayed(queue_name=job.queue, job_id=job.id, delay_seconds=delay)
                logger.warning(
                    f"[{self.worker_id}] Job {job.id} failed with retryable error ({type(exc).__name__}: {exc}). "
                    f"Retry {job.retry_count}/{job.max_retries} scheduled in {delay:.2f}s (due: {next_retry.isoformat()})"
                )
                return True

            # Retries exhausted or non-retryable fatal error
            attempt.status = AttemptStatus.FAILED
            attempt.finished_at = finish_dt
            attempt.duration = duration
            attempt.error = error_traceback
            attempt.save(update_fields=['status', 'finished_at', 'duration', 'error'])

            job.status = JobStatus.FAILED
            job.error = str(exc)
            job.completed_at = finish_dt
            job.save(update_fields=['status', 'error', 'completed_at'])

            reason = f"retries exhausted ({job.retry_count}/{job.max_retries})" if job.retry_count >= job.max_retries else "non-retryable fatal error"
            logger.error(f"[{self.worker_id}] Job {job.id} ({job.type}) PERMANENTLY FAILED ({reason}): {exc}")
            return True

    def run(self, burst: bool = False, max_jobs: Optional[int] = None) -> int:
        """
        Starts the worker polling loop.
        Continuously checks and promotes due delayed retries before popping active jobs.
        :param burst: If True, exits as soon as all active queues and delayed queues are empty.
        :param max_jobs: Optional maximum number of jobs to process before exiting.
        :return: Total number of jobs processed.
        """
        self.is_running = True
        jobs_processed = 0

        logger.info(f"[{self.worker_id}] Worker started. Listening on queues: {self.queues} (burst={burst})")

        while self.is_running:
            try:
                # 1. Promote any due delayed retries from Redis ZSET to active list queues
                self.queue.promote_due_jobs()

                # 2. Dequeue from active FIFO queues
                dequeued = self.queue.dequeue(self.queues, timeout=self.timeout)

                if not dequeued:
                    # In burst mode, ensure no delayed jobs remain pending before exiting
                    if burst:
                        # Check if any delayed jobs are pending
                        if self.queue.delayed_length() == 0:
                            logger.info(f"[{self.worker_id}] Burst mode active & queues empty. Exiting worker loop.")
                            break
                    continue

                queue_name, job_id_str = dequeued
                processed = self.process_job(job_id_str, queue_name)
                if processed:
                    jobs_processed += 1

                if max_jobs is not None and jobs_processed >= max_jobs:
                    logger.info(f"[{self.worker_id}] Reached maximum job limit ({max_jobs}). Stopping worker.")
                    break

            except Exception as exc:
                logger.error(f"[{self.worker_id}] Unexpected error in worker loop: {exc}\n{traceback.format_exc()}")
                if not self.is_running:
                    break
                time.sleep(1)

        logger.info(f"[{self.worker_id}] Worker stopped. Total jobs processed: {jobs_processed}")
        return jobs_processed
