import sys
from django.core.management.base import BaseCommand
from apps.jobs.worker import CustomWorker


class Command(BaseCommand):
    help = "Run ForgeFlow independent async worker to consume and execute jobs from Redis queues."

    def add_arguments(self, parser):
        parser.add_argument(
            "--queues",
            type=str,
            default="default",
            help="Comma-separated list of Redis queues to listen to (e.g. 'default,high,low').",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=2,
            help="Timeout in seconds for blocking queue pop (BRPOP). Default is 2.",
        )
        parser.add_argument(
            "--burst",
            action="store_true",
            help="Run in burst mode: process all pending jobs and exit once the queues are empty.",
        )
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=None,
            help="Maximum number of jobs to process before terminating.",
        )
        parser.add_argument(
            "--worker-id",
            type=str,
            default=None,
            help="Optional custom worker identifier.",
        )

    def handle(self, *args, **options):
        queues = options["queues"]
        timeout = options["timeout"]
        burst = options["burst"]
        max_jobs = options["max_jobs"]
        worker_id = options["worker_id"]

        self.stdout.write(self.style.SUCCESS("\n======================================================="))
        self.stdout.write(self.style.SUCCESS("       ⚡ FORGEFLOW DISTRIBUTED WORKER ENGINE ⚡       "))
        self.stdout.write(self.style.SUCCESS("=======================================================\n"))
        self.stdout.write(f"Listening on queues : {queues}")
        self.stdout.write(f"Polling timeout     : {timeout}s")
        self.stdout.write(f"Burst mode          : {burst}")
        self.stdout.write(f"Max jobs limit      : {max_jobs if max_jobs else 'Unlimited'}")
        self.stdout.write("Press Ctrl+C to stop gracefully.\n")

        worker = CustomWorker(
            queues=queues,
            timeout=timeout,
            worker_id=worker_id,
        )

        try:
            processed = worker.run(burst=burst, max_jobs=max_jobs)
            self.stdout.write(self.style.SUCCESS(f"\n[Worker] Finished. Total jobs processed: {processed}"))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n[Worker] Worker interrupted by user. Exiting."))
