/*
 * corpus_runner.c -- ARMShift generic ARM64 architecture differential, corpus runner.
 *
 * Executes the bounded ARM64 architecture-test corpus defined in corpus-manifest.json
 * (version 1) and prints one line per test to stdout:
 *
 *     <id>\t<canonical>
 *
 * where <canonical> is:
 *     reg_only          "0x%016" PRIx64
 *     reg_with_flags    "0x%016" PRIx64 " nzcv=0x%x"   (NZCV nibble = (nzcv>>28)&0xf)
 *
 * The SAME binary is run on BOTH sides of the differential:
 *   (a) under a pinned qemu-system-aarch64 build (TCG) -- the system under test (SUT);
 *   (b) on genuine ARM64 hardware -- the semantic reference (the oracle).
 * collect_results.py wraps this stdout into a gae-diff/results@1 result set and
 * (on the SUT side, in seed mode) injects the one documented negative-control
 * mutation. diff_corpus.py then diffs the two sides.
 *
 * Inputs are baked as C constants and fed to the instruction under test via inline
 * asm register operands, so no fragile large-immediate MOV expansion is relied on.
 * Build at -O0 with volatile asm so the operations are not folded away. Build as a
 * STATIC binary on the ARM64 reference and run that same binary on both sides, so the
 * diff isolates translation semantics rather than build differences.
 *
 * Build:  cc -O0 -std=c11 -Wall -Wextra -static -o corpus_runner corpus_runner.c
 * Run:    ./corpus_runner
 */
#include <stdio.h>
#include <stdint.h>
#include <inttypes.h>

#if !defined(__aarch64__)
#error "corpus_runner.c targets aarch64 -- build it on the ARM64 reference / in the aarch64 guest."
#endif

static void reg(const char *id, uint64_t r) {
    printf("%s\t0x%016" PRIx64 "\n", id, r);
}
static void flags(const char *id, uint64_t r, uint64_t nzcv) {
    printf("%s\t0x%016" PRIx64 " nzcv=0x%x\n", id, r, (unsigned)((nzcv >> 28) & 0xf));
}

int main(void) {
    uint64_t r, f;

    /* integer-arith */
    { uint64_t a = 1, b = 2;
      __asm__ volatile("add %0, %1, %2" : "=r"(r) : "r"(a), "r"(b)); reg("add_basic", r); }
    { uint64_t a = 0xffffffffffffffffULL, b = 1;
      __asm__ volatile("add %0, %1, %2" : "=r"(r) : "r"(a), "r"(b)); reg("add_wrap", r); }
    { uint64_t a = 5, b = 9;
      __asm__ volatile("sub %0, %1, %2" : "=r"(r) : "r"(a), "r"(b)); reg("sub_neg", r); }

    /* integer-mul */
    { uint64_t a = 0x100000000ULL, b = 0x100000000ULL;
      __asm__ volatile("mul %0, %1, %2" : "=r"(r) : "r"(a), "r"(b)); reg("mul_low", r); }
    { uint64_t a = 0x100000000ULL, b = 0x100000000ULL;
      __asm__ volatile("umulh %0, %1, %2" : "=r"(r) : "r"(a), "r"(b)); reg("umulh_high", r); }

    /* logical */
    { uint64_t a = 0xf0f0f0f0f0f0f0f0ULL, b = 0x0ff00ff00ff00ff0ULL;
      __asm__ volatile("and %0, %1, %2" : "=r"(r) : "r"(a), "r"(b)); reg("and_op", r); }
    { uint64_t a = 0xf0f0f0f0f0f0f0f0ULL, b = 0x0ff00ff00ff00ff0ULL;
      __asm__ volatile("orr %0, %1, %2" : "=r"(r) : "r"(a), "r"(b)); reg("orr_op", r); }
    { uint64_t a = 0xf0f0f0f0f0f0f0f0ULL, b = 0x0ff00ff00ff00ff0ULL;
      __asm__ volatile("eor %0, %1, %2" : "=r"(r) : "r"(a), "r"(b)); reg("eor_op", r); }

    /* shift (immediate) */
    { uint64_t a = 1;
      __asm__ volatile("lsl %0, %1, #40" : "=r"(r) : "r"(a)); reg("lsl_op", r); }
    { uint64_t a = 0x8000000000000000ULL;
      __asm__ volatile("lsr %0, %1, #63" : "=r"(r) : "r"(a)); reg("lsr_op", r); }
    { uint64_t a = 0x8000000000000000ULL;
      __asm__ volatile("asr %0, %1, #63" : "=r"(r) : "r"(a)); reg("asr_op", r); }
    { uint64_t a = 1;
      __asm__ volatile("ror %0, %1, #1" : "=r"(r) : "r"(a)); reg("ror_op", r); }

    /* bitmanip */
    { uint64_t a = 1;
      __asm__ volatile("clz %0, %1" : "=r"(r) : "r"(a)); reg("clz_op", r); }
    { uint64_t a = 1;
      __asm__ volatile("rbit %0, %1" : "=r"(r) : "r"(a)); reg("rbit_op", r); }
    { uint64_t a = 0x0102030405060708ULL;
      __asm__ volatile("rev %0, %1" : "=r"(r) : "r"(a)); reg("rev_op", r); }

    /* 32-bit W-register add (wrap + zero-extend to X) */
    { uint32_t a = 0xffffffffu, w;
      __asm__ volatile("add %w0, %w1, #1" : "=r"(w) : "r"(a)); reg("w_add_wrap", (uint64_t)w); }

    /* conditional select (EQ false -> selects Xm) */
    { uint64_t a = 0xaaaa, b = 0xbbbb;
      __asm__ volatile("cmp %1, %2\n\tcsel %0, %1, %2, eq" : "=r"(r) : "r"(a), "r"(b) : "cc");
      reg("csel_false", r); }

    /* flag-setting compares/adds -- capture NZCV in the same asm block */
    { uint64_t a = 5, b = 5;
      __asm__ volatile("subs %0, %2, %3\n\tmrs %1, nzcv"
                       : "=&r"(r), "=&r"(f) : "r"(a), "r"(b) : "cc"); flags("cmp_eq_flags", r, f); }
    { uint64_t a = 5, b = 9;
      __asm__ volatile("subs %0, %2, %3\n\tmrs %1, nzcv"
                       : "=&r"(r), "=&r"(f) : "r"(a), "r"(b) : "cc"); flags("subs_neg_flags", r, f); }
    { uint64_t a = 0xffffffffffffffffULL, b = 1;
      __asm__ volatile("adds %0, %2, %3\n\tmrs %1, nzcv"
                       : "=&r"(r), "=&r"(f) : "r"(a), "r"(b) : "cc"); flags("adds_carry", r, f); }
    { uint64_t a = 0x7fffffffffffffffULL, b = 1;
      __asm__ volatile("adds %0, %2, %3\n\tmrs %1, nzcv"
                       : "=&r"(r), "=&r"(f) : "r"(a), "r"(b) : "cc"); flags("adds_overflow", r, f); }

    /* negative control: architecturally identical to add_basic (1+2=3).
       The runner emits the TRUE value; collect_results.py --side sut --seed injects
       the documented single-bit mutation on the SUT side only. */
    { uint64_t a = 1, b = 2;
      __asm__ volatile("add %0, %1, %2" : "=r"(r) : "r"(a), "r"(b)); reg("seed_negctrl", r); }

    return 0;
}
