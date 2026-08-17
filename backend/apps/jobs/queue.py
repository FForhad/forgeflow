import logging
import time
from typing import List, Optional, Tuple, Union
from uuid import UUID
from django.utils import timezone
from apps.core.redis_client import get_redis_client
from apps.jobs.models import Job, JobStatus

logger = logging.getLogger(__name__)


class RedisJobQueue:
    """
    Manual Redis Queue Implementation for ForgeFlow.
    Uses LPUSH for enqueuing, BRPOP for blocking FIFO dequeuing,
    and a Redis Sorted Set (ZSET) for delayed retries with exponential backoff.
    """

    def __init__(self, key_prefix: str = "jobs"):
        self.key_prefix = key_prefix
        self._redis = None

    @property
    def redis(self):
        if self._redis is None:
            self._redis = get_redis_client()
        return self._redis

    def get_queue_key(self, queue_name: str) -> str:
        """Returns the Redis key for the specified active queue name."""
        return f"{self.key_prefix}:{queue_name}"

    def get_delayed_key(self) -> str:
        """Returns the Redis ZSET key for delayed / scheduled jobs."""
        return f"{self.key_prefix}:delayed"

    def enqueue(self, queue_name: str, job_id: Union[str, UUID]) -> int:
        """
        Pushes a job_id to the tail/head of the queue using LPUSH.
        Returns the new length of the queue.
        """
        queue_key = self.get_queue_key(queue_name)
        new_length = self.redis.lpush(queue_key, str(job_id))
        logger.debug(f"[Queue] Enqueued job {job_id} into '{queue_key}' (queue depth: {new_length})")
        return new_length

    def dequeue(
        self,
        queue_names: Union[str, List[str]],
        timeout: int = 2,
    ) -> Optional[Tuple[str, str]]:
        """
        Blocks until a job_id is available from one of the given queues using BRPOP.
        Returns a tuple of (queue_name, job_id) or None if timeout expired.
        """
        if isinstance(queue_names, str):
            queue_names = [queue_names]

        keys = [self.get_queue_key(q) for q in queue_names]
        result = self.redis.brpop(keys, timeout=timeout)

        if not result:
            return None

        matched_key, job_id = result
        q_name = matched_key.split(f"{self.key_prefix}:", 1)[-1] if f"{self.key_prefix}:" in matched_key else matched_key
        logger.debug(f"[Queue] Dequeued job {job_id} from '{matched_key}'")
        return q_name, job_id

    def length(self, queue_name: str) -> int:
        """Returns the current number of pending items in the active queue."""
        return self.redis.llen(self.get_queue_key(queue_name))

    def clear(self, queue_name: str) -> bool:
        """Flushes all pending items in the active queue."""
        queue_key = self.get_queue_key(queue_name)
        return bool(self.redis.delete(queue_key))

    def peek(self, queue_name: str, count: int = 10) -> List[str]:
        """Peeks at the next items to be consumed without popping them."""
        queue_key = self.get_queue_key(queue_name)
        return self.redis.lrange(queue_key, -count, -1)

    # -------------------------------------------------------------------------
    # DELAYED / RETRY QUEUE METHODS (REDIS ZSET)
    # -------------------------------------------------------------------------

    def schedule_delayed(
        self,
        queue_name: str,
        job_id: Union[str, UUID],
        delay_seconds: float,
    ) -> bool:
        """
        Schedules a job for delayed retry by adding it to a Redis Sorted Set (ZSET).
        Score is the Unix timestamp when the job becomes due.
        """
        due_timestamp = time.time() + max(0.0, float(delay_seconds))
        member = f"{queue_name}:{job_id}"
        self.redis.zadd(self.get_delayed_key(), {member: due_timestamp})
        logger.info(
            f"[Queue] Scheduled delayed retry for job {job_id} in {delay_seconds:.2f}s "
            f"(target queue: '{queue_name}', due at: {due_timestamp:.2f})"
        )
        return True

    def promote_due_jobs(self, max_jobs: int = 100) -> int:
        """
        Scans the delayed ZSET for jobs whose due timestamp <= current time.
        Atomically removes them from the ZSET and LPUSHes them into their target active queue.
        Returns the count of promoted jobs.
        """
        now = time.time()
        delayed_key = self.get_delayed_key()
        due_items = self.redis.zrangebyscore(delayed_key, 0, now, start=0, num=max_jobs)

        if not due_items:
            return 0

        promoted_count = 0
        for item in due_items:
            # Atomically remove from ZSET to prevent duplicate promotions across workers
            removed = self.redis.zrem(delayed_key, item)
            if removed:
                if ":" in item:
                    queue_name, job_id = item.split(":", 1)
                else:
                    queue_name, job_id = "default", item

                self.enqueue(queue_name, job_id)
                promoted_count += 1

                # Update database state from RETRYING to QUEUED
                try:
                    Job.objects.filter(id=job_id, status=JobStatus.RETRYING).update(
                        status=JobStatus.QUEUED,
                        queued_at=timezone.now(),
                    )
                except Exception as exc:
                    logger.warning(f"[Queue] Failed to update DB status for promoted job {job_id}: {exc}")

        if promoted_count > 0:
            logger.info(f"[Queue] Promoted {promoted_count} due delayed job(s) to active queues.")
        return promoted_count

    def delayed_length(self) -> int:
        """Returns the total number of currently scheduled delayed jobs in the ZSET."""
        return self.redis.zcard(self.get_delayed_key())

    def clear_delayed(self) -> bool:
        """Flushes all delayed jobs from the ZSET."""
        return bool(self.redis.delete(self.get_delayed_key()))


# Global default queue instance
default_job_queue = RedisJobQueue()


def enqueue_job(job: Job, queue_instance: Optional[RedisJobQueue] = None) -> bool:
    """
    Enqueues a Job instance into Redis and updates its database state to QUEUED.
    """
    q = queue_instance or default_job_queue
    try:
        job.status = JobStatus.QUEUED
        job.queued_at = timezone.now()
        job.save(update_fields=['status', 'queued_at'])
        q.enqueue(job.queue, str(job.id))
        logger.info(f"Enqueued job {job.id} to queue '{job.queue}'")
        return True
    except Exception as exc:
        logger.error(f"Failed to enqueue job {job.id} into Redis: {exc}")
        job.status = JobStatus.PENDING
        job.save(update_fields=['status'])
        raise exc
