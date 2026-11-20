import java.lang.management.ManagementFactory;
import java.util.ArrayDeque;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;

/** Synthetic retained-object leak; no user data or external services. */
public final class MemoryLab {
    private static final ArrayDeque<Payload> RETAINED = new ArrayDeque<>();
    private static final int CHUNK_BYTES = 64 * 1024;
    private static final int BOUNDED_ITEMS = 64;
    private static final AtomicBoolean RUNNING = new AtomicBoolean(true);

    static final class Payload {
        final long sequence;
        final byte[] bytes = new byte[CHUNK_BYTES];
        Payload(long sequence) {
            this.sequence = sequence;
            for (int i = 0; i < bytes.length; i += 4096) bytes[i] = (byte) sequence;
        }
    }

    public static void main(String[] args) throws InterruptedException {
        if (args.length != 2 || !(args[0].equals("leak") || args[0].equals("bounded"))) {
            throw new IllegalArgumentException("Usage: MemoryLab leak|bounded durationSeconds");
        }
        boolean bounded = args[0].equals("bounded");
        int seconds = Integer.parseInt(args[1]);
        if (seconds < 1 || seconds > 300) throw new IllegalArgumentException("duration: 1..300 seconds");
        long start = System.nanoTime();
        System.err.printf("mode=%s pid=%d max_heap_bytes=%d java=%s%n", args[0],
                ProcessHandle.current().pid(), Runtime.getRuntime().maxMemory(), System.getProperty("java.version"));
        System.out.println("elapsed_seconds,retained_objects,payload_bytes,heap_used_bytes,gc_count,gc_time_ms");

        Thread sampler = new Thread(() -> {
            while (RUNNING.get()) {
                sample(start);
                try { Thread.sleep(1000); }
                catch (InterruptedException ex) { Thread.currentThread().interrupt(); break; }
            }
        }, "heap-sampler");
        sampler.setDaemon(true);
        Thread allocator = new Thread(() -> {
            long sequence = 0;
            try {
                while ((System.nanoTime() - start) / 1e9 < seconds) {
                    // 8 * 64 KiB / 0.4 s = approximately 1.25 MiB/s.
                    for (int i = 0; i < 8; i++) {
                        Payload payload = new Payload(sequence++);
                        synchronized (RETAINED) {
                            if (bounded && RETAINED.size() == BOUNDED_ITEMS) RETAINED.removeFirst();
                            RETAINED.addLast(payload);
                        }
                    }
                    Thread.sleep(400);
                }
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
            } finally {
                RUNNING.set(false);
            }
        }, "payload-allocator");
        // Run with -XX:+ExitOnOutOfMemoryError: any thread exhausting the heap terminates this demo.
        sampler.start();
        allocator.start();
        allocator.join();
        sampler.interrupt();
        sampler.join();
        sample(start);
        System.err.println("completed normally");
    }

    private static void sample(long start) {
        int objects;
        long payloadBytes;
        synchronized (RETAINED) {
            objects = RETAINED.size();
            // Stream runs under the same lock as mutations: no concurrent traversal of ArrayDeque.
            payloadBytes = RETAINED.stream().mapToLong(payload -> payload.bytes.length).sum();
        }
        var collectors = ManagementFactory.getGarbageCollectorMXBeans();
        long count = collectors.stream().mapToLong(gc -> Math.max(0, gc.getCollectionCount())).sum();
        long time = collectors.stream().mapToLong(gc -> Math.max(0, gc.getCollectionTime())).sum();
        long used = ManagementFactory.getMemoryMXBean().getHeapMemoryUsage().getUsed();
        System.out.printf(Locale.ROOT, "%.3f,%d,%d,%d,%d,%d%n",
                (System.nanoTime() - start) / 1e9, objects, payloadBytes, used, count, time);
    }
}
