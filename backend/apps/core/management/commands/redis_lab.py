import time
from django.core.management.base import BaseCommand
from apps.core.redis_client import get_redis_client


class Command(BaseCommand):
    help = "Interactive Redis Fundamentals Lab covering primitives, data structures, queues, transactions, and pub/sub."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("\n======================================================="))
        self.stdout.write(self.style.SUCCESS("       ⚡ FORGEFLOW REDIS FUNDAMENTALS LAB ⚡          "))
        self.stdout.write(self.style.SUCCESS("=======================================================\n"))

        r = get_redis_client()
        r.ping()
        self.stdout.write(self.style.SUCCESS("✅ Successfully connected to Redis instance at 127.0.0.1:6379\n"))

        # ---------------------------------------------------------------------
        # 1. STRINGS & EXPIRATION
        # ---------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("1. STRINGS, COUNTERS & EXPIRATION (SET, GET, DEL, INCR, EXPIRE, TTL)"))
        r.set("forgeflow:lab:system_name", "ForgeFlow Distributed Engine")
        val = r.get("forgeflow:lab:system_name")
        self.stdout.write(f"   [SET / GET] key 'forgeflow:lab:system_name' -> {val}")

        r.set("forgeflow:lab:job_counter", 100)
        new_cnt = r.incr("forgeflow:lab:job_counter")
        self.stdout.write(f"   [INCR] key 'forgeflow:lab:job_counter' (100 + 1) -> {new_cnt}")

        r.set("forgeflow:lab:temp_token", "jwt_expiring_sample", ex=2)
        ttl = r.ttl("forgeflow:lab:temp_token")
        self.stdout.write(f"   [EXPIRE / TTL] key 'forgeflow:lab:temp_token' has TTL -> {ttl}s")
        time.sleep(2.1)
        expired_val = r.get("forgeflow:lab:temp_token")
        self.stdout.write(f"   [TTL EXPIRED] after 2 seconds, key 'forgeflow:lab:temp_token' -> {expired_val} (None)")

        # ---------------------------------------------------------------------
        # 2. LISTS & QUEUE PRIMITIVES
        # ---------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. LISTS & QUEUES (LPUSH, RPUSH, LPOP, RPOP, BRPOP, LLEN)"))
        queue_key = "forgeflow:lab:demo_queue"
        r.delete(queue_key)

        # Producer pushes to head (LPUSH)
        r.lpush(queue_key, "job-uuid-001")
        r.lpush(queue_key, "job-uuid-002")
        r.lpush(queue_key, "job-uuid-003")
        length = r.llen(queue_key)
        items = r.lrange(queue_key, 0, -1)
        self.stdout.write(f"   [LPUSH x3] Queue items (head-to-tail): {items}, length: {length}")

        # FIFO Consumer pops from tail (RPOP)
        first_out = r.rpop(queue_key)
        self.stdout.write(f"   [RPOP (FIFO)] First item consumed -> {first_out} (Expected: job-uuid-001)")

        # Blocking pop with timeout (BRPOP)
        popped = r.brpop(queue_key, timeout=1)
        self.stdout.write(f"   [BRPOP (Blocking FIFO)] Popped -> queue: {popped[0]}, item: {popped[1]}")

        # ---------------------------------------------------------------------
        # 3. HASHES (OBJECT CACHING)
        # ---------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n3. HASHES (HSET, HGET, HGETALL, HDEL)"))
        hash_key = "forgeflow:lab:worker:worker-01"
        r.hset(hash_key, mapping={
            "status": "RUNNING",
            "current_job": "job-uuid-002",
            "active_threads": "4",
            "started_at": "2026-08-18T00:00:00Z"
        })
        worker_status = r.hget(hash_key, "status")
        all_worker_data = r.hgetall(hash_key)
        self.stdout.write(f"   [HSET / HGET] Worker status -> {worker_status}")
        self.stdout.write(f"   [HGETALL] Full worker metadata -> {all_worker_data}")

        # ---------------------------------------------------------------------
        # 4. SETS & SORTED SETS (PRIORITY SCHEDULING)
        # ---------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n4. SETS & SORTED SETS (SADD, SMEMBERS, ZADD, ZRANGEBYSCORE)"))
        set_key = "forgeflow:lab:active_nodes"
        r.sadd(set_key, "node-east-1", "node-west-1", "node-east-1")
        nodes = r.smembers(set_key)
        self.stdout.write(f"   [SETS (Unique)] Active cluster nodes: {nodes}")

        zset_key = "forgeflow:lab:priority_queue"
        r.delete(zset_key)
        # Score = priority (e.g. 1=low, 2=medium, 4=critical)
        r.zadd(zset_key, {
            "low_priority_job": 1,
            "critical_security_audit": 4,
            "medium_report_job": 2,
        })
        # Highest score first (ZREVRANGE)
        highest_priority = r.zrevrange(zset_key, 0, -1, withscores=True)
        self.stdout.write(f"   [SORTED SETS (Priority Queue)] Order (highest first): {highest_priority}")

        # ---------------------------------------------------------------------
        # 5. ATOMIC TRANSACTIONS & PIPELINING (MULTI / EXEC)
        # ---------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. TRANSACTIONS & PIPELINES (MULTI / EXEC)"))
        pipe = r.pipeline(transaction=True)
        pipe.set("forgeflow:lab:tx_step1", "step_1_ok")
        pipe.set("forgeflow:lab:tx_step2", "step_2_ok")
        pipe.incr("forgeflow:lab:tx_counter")
        tx_results = pipe.execute()
        self.stdout.write(f"   [MULTI/EXEC Pipeline] Atomic batch execution results -> {tx_results}")

        # ---------------------------------------------------------------------
        # 6. PUB/SUB (REALTIME BROADCASTING)
        # ---------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n6. PUB/SUB EVENT STREAMING (PUBLISH / SUBSCRIBE)"))
        channel = "forgeflow:events:job_updates"
        pubsub = r.pubsub()
        pubsub.subscribe(channel)
        
        # Give subscription a split millisecond to establish
        time.sleep(0.05)
        r.publish(channel, '{"event": "JOB_COMPLETED", "job_id": "job-uuid-001"}')
        
        # Read message
        msg1 = pubsub.get_message(timeout=1.0) # Subscription confirm message
        msg2 = pubsub.get_message(timeout=1.0) # Actual payload message
        pubsub.unsubscribe()
        self.stdout.write(f"   [PUB/SUB] Listener received event on '{channel}': {msg2.get('data') if msg2 else None}")

        # ---------------------------------------------------------------------
        # 7. PERSISTENCE & SYSTEM DIAGNOSTICS
        # ---------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n7. REDIS PERSISTENCE & MEMORY DIAGNOSTICS"))
        info_mem = r.info("memory")
        info_persist = r.info("persistence")
        self.stdout.write(f"   [INFO memory] Used Memory: {info_mem.get('used_memory_human')}, Peak: {info_mem.get('used_memory_peak_human')}")
        self.stdout.write(f"   [INFO persistence] RDB Last Save Status: {info_persist.get('rdb_last_bgsave_status')}, AOF Enabled: {info_persist.get('aof_enabled')}")

        # Cleanup demo lab keys
        r.delete(queue_key, hash_key, set_key, zset_key, "forgeflow:lab:system_name", "forgeflow:lab:job_counter", "forgeflow:lab:tx_step1", "forgeflow:lab:tx_step2", "forgeflow:lab:tx_counter")

        self.stdout.write(self.style.SUCCESS("\n======================================================="))
        self.stdout.write(self.style.SUCCESS("  🎉 REDIS FUNDAMENTALS LAB COMPLETED SUCCESSFULLY!    "))
        self.stdout.write(self.style.SUCCESS("=======================================================\n"))
