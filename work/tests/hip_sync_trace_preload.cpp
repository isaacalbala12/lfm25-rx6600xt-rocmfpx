#define _GNU_SOURCE

#include <dlfcn.h>
#include <execinfo.h>
#include <fcntl.h>
#include <atomic>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

// hipStream_t is an opaque pointer and hipError_t is an int-sized enum.  The
// wrapper intentionally avoids including a particular ROCm SDK header so it
// can be used with the bundled ROCm runtime and with the native HIP builds.
using hipStream_t = void *;
using hipError_t = int;
using sync_fn = hipError_t (*)(hipStream_t);

static sync_fn real_sync = nullptr;
static pthread_once_t resolve_once = PTHREAD_ONCE_INIT;
static pthread_mutex_t log_mutex = PTHREAD_MUTEX_INITIALIZER;
static std::atomic<uint64_t> sequence{0};
static int log_fd = -1;
static __thread int inside_wrapper = 0;

static uint64_t now_ns() {
    struct timespec ts{};
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ULL + static_cast<uint64_t>(ts.tv_nsec);
}

static void resolve_real() {
    real_sync = reinterpret_cast<sync_fn>(dlsym(RTLD_NEXT, "hipStreamSynchronize"));
    const char *path = getenv("HIP_SYNC_WRAPPER_LOG");
    if (path != nullptr && *path != '\0') {
        log_fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0644);
    }
}

static void write_stack(FILE *file, void * const *frames, int count) {
    char **symbols = backtrace_symbols(frames, count);
    if (symbols == nullptr) {
        return;
    }
    for (int i = 0; i < count; ++i) {
        fprintf(file, "  frame=%d %s\n", i, symbols[i]);
    }
    free(symbols);
}

extern "C" hipError_t hipStreamSynchronize(hipStream_t stream) {
    if (inside_wrapper) {
        return real_sync != nullptr ? real_sync(stream) : -1;
    }
    inside_wrapper = 1;
    pthread_once(&resolve_once, resolve_real);
    if (real_sync == nullptr) {
        inside_wrapper = 0;
        return -1;
    }

    const uint64_t id = sequence.fetch_add(1, std::memory_order_relaxed) + 1;
    const uint64_t start = now_ns();
    const hipError_t result = real_sync(stream);
    const uint64_t end = now_ns();
    const uint64_t duration = end - start;

    if (log_fd >= 0 && (duration >= 1000000ULL || getenv("HIP_SYNC_WRAPPER_LOG_ALL") != nullptr)) {
        void *frames[32]{};
        const int frame_count = backtrace(frames, 32);
        FILE *file = fdopen(dup(log_fd), "a");
        if (file != nullptr) {
            pthread_mutex_lock(&log_mutex);
            fprintf(file, "SYNC id=%llu start_ns=%llu end_ns=%llu duration_ns=%llu stream=%p result=%d\n",
                    static_cast<unsigned long long>(id),
                    static_cast<unsigned long long>(start),
                    static_cast<unsigned long long>(end),
                    static_cast<unsigned long long>(duration), stream, result);
            write_stack(file, frames, frame_count);
            fflush(file);
            pthread_mutex_unlock(&log_mutex);
            fclose(file);
        }
    }
    inside_wrapper = 0;
    return result;
}
