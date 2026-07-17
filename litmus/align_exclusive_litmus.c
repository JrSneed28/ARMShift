/*
 * align_exclusive_litmus.c -- genuine-silicon alignment litmus (generic-arm64-engine).
 *
 * AMD-PREVIEW co-tags: ENDURANCE-DEFERRED · NOT-ENDURANCE-QUALIFIED ·
 * DUAL-HOST-NOT-QUALIFIED · INTEL-DEFERRED · SINGLE-AMD-UARCH (Zen 4 / Ryzen 7 7800X3D).
 * SCOPE: generic ARM64 only.  This litmus targets the generic AArch64 architecture
 * exclusively; it carries no platform-specific machine profile, guest-OS-specific
 * source/config, or platform-specific guest input.
 *
 * Single, focused architectural litmus: a misaligned exclusive load (LDXR at a
 * non-naturally-aligned address, buf+1) is architecturally UNALIGNED regardless of
 * SCTLR.A and MUST raise an Alignment fault (delivered to userspace as
 * SIGBUS / BUS_ADRALN). This program installs a SIGBUS/SIGSEGV handler, provokes the
 * access with sigsetjmp/siglongjmp recovery, prints the observed (signal, si_code),
 * and exits non-zero if the required fault was NOT observed.
 *
 * On genuine ARM64 silicon the expected observation is:
 *     signal=SIGBUS;si_code=BUS_ADRALN   (exit 0)
 * A "no_fault" observation (the access completing silently) is an architectural
 * violation on this litmus and exits non-zero.
 *
 * Build:  cc -O2 -std=c11 -Wall -Wextra -o align_exclusive_litmus align_exclusive_litmus.c
 * Run:    ./align_exclusive_litmus
 */
#define _GNU_SOURCE
#include <setjmp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#if !defined(__aarch64__)
#error "align_exclusive_litmus.c targets aarch64 -- build it on genuine ARM64 silicon."
#endif

static sigjmp_buf g_jmp;
static volatile int g_signo;
static volatile int g_code;

static void handler(int signo, siginfo_t *si, void *uc) {
    (void)uc;
    g_signo = signo;
    g_code = si->si_code;
    siglongjmp(g_jmp, 1);
}

static const char *signame(int s) {
    switch (s) {
        case SIGSEGV: return "SIGSEGV";
        case SIGBUS:  return "SIGBUS";
        case SIGILL:  return "SIGILL";
        default:      return "SIG?";
    }
}
static const char *codename(int signo, int code) {
    if (signo == SIGBUS) {
        if (code == BUS_ADRALN) return "BUS_ADRALN";
        if (code == BUS_ADRERR) return "BUS_ADRERR";
    }
    if (signo == SIGSEGV) {
        if (code == SEGV_MAPERR) return "SEGV_MAPERR";
        if (code == SEGV_ACCERR) return "SEGV_ACCERR";
    }
    return "OTHER";
}

int main(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = handler;
    sa.sa_flags = SA_SIGINFO | SA_NODEFER;
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    sigaction(SIGILL, &sa, NULL);

    static uint64_t buf[4] __attribute__((aligned(64)));
    volatile uint8_t *mis = ((volatile uint8_t *)buf) + 1;   /* +1 => misaligned */

    if (sigsetjmp(g_jmp, 1) == 0) {
        uint64_t tmp;
        __asm__ __volatile__("ldxr %0, [%1]\n\t"
                             "clrex\n\t"
                             : "=r"(tmp) : "r"(mis) : "memory");
        (void)tmp;
        /* Reached here => the misaligned exclusive load did NOT fault. */
        printf("id=alignment_exclusive state=no_fault\n");
        fprintf(stderr,
                "REJECTED: misaligned LDXR did not fault; architecture requires "
                "SIGBUS/BUS_ADRALN regardless of SCTLR.A.\n");
        return 1;
    }

    printf("id=alignment_exclusive signal=%s si_code=%s\n",
           signame(g_signo), codename(g_signo, g_code));

    if (g_signo == SIGBUS && g_code == BUS_ADRALN) {
        fprintf(stderr, "OK: alignment fault observed on genuine silicon.\n");
        return 0;
    }
    fprintf(stderr, "REJECTED: expected SIGBUS/BUS_ADRALN, observed %s/%s.\n",
            signame(g_signo), codename(g_signo, g_code));
    return 1;
}
