import logging
from typing import List, Optional, Tuple, Union
from uuid import UUID
from django.utils import timezone
from apps.core.redis_client import get_redis_client
from apps.jobs.models import Job, JobStatus

logger = logging.getLogger(__name__)


class RedisJobQueue:
    """
    Manual Redis Queue Implementation for ForgeFlow.
    Uses LPUSH for enqueuing and BRPOP for blocking FIFO dequeuing.
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
        """Returns the Redis key for the specified queue name."""
        return f"{self.key_prefix}:{queue_name}"

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
        # Extract the original queue name from "jobs:<queue_name>"
        q_name = matched_key.split(f"{self.key_prefix}:", 1)[-1] if f"{self.key_prefix}:" in matched_key else matched_key
        logger.debug(f"[Queue] Dequeued job {job_id} from '{matched_key}'")
        return q_name, job_id

    def length(self, queue_name: str) -> int:
        """Returns the current number of pending items in the queue."""
        return self.redis.llen(self.get_queue_key(queue_name))

    def clear(self, queue_name: str) -> bool:
        """Flushes all pending items in the queue."""
        queue_key = self.get_queue_key(queue_name)
        return bool(self.redis.delete(queue_key))

    def peek(self, queue_name: str, count: int = 10) -> List[str]:
        """Peeks at the next items to be consumed without popping them."""
        queue_key = self.get_queue_key(queue_name)
        # In an LPUSH / RPOP queue, the next items to be popped are at the tail (negative indexes)
        return self.redis.lrange(queue_key, -count, -1)


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
        # Keep job saved in DB with PENDING status if Redis fails
        job.status = JobStatus.PENDING
        job.save(update_fields=['status'])
        raise exc
