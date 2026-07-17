/*
 * valid_corpus_runner.c -- WA.2 translation-validation runner (five families).
 *
 * PROVISIONAL · AMD-ONLY · NOT GATE EVIDENCE.
 * AMD-PREVIEW co-tags: ENDURANCE-DEFERRED · NOT-ENDURANCE-QUALIFIED ·
 * DUAL-HOST-NOT-QUALIFIED · INTEL-DEFERRED · SINGLE-AMD-UARCH (Zen 4 / Ryzen 7 7800X3D).
 *
 * SCOPE: generic ARM64 only (generic-arm64-engine).  This harness targets the generic
 * AArch64 architecture exclusively; it carries no platform-specific machine profile,
 * guest-OS-specific source/config, or platform-specific guest input.
 *
 * This NEW file EXTENDS the W0.4 harness; it does not edit tools/diff/* (frozen,
 * byte-identical to public ARMShift).  It executes the WA.2 required
 * set defined in translation-validation-manifest.json / valid-corpus-manifest.json
 * across integer, branch/exception, FP/SIMD, atomics/exclusives, and architected
 * system-register cases.
 *
 * TWO MODES:
 *   emit  (default) : prints one line per test "<id>\t<canonical>".  This feeds the
 *                     INDEPENDENT DIFFERENTIAL: the SAME static binary runs (a) under
 *                     the frozen qemu-system-aarch64 SUT and (b) on a real ARM64
 *                     reference; tools/diff/collect_results.py wraps stdout and
 *                     tools/diff/diff_corpus.py diffs the two.  The reference RUN is
 *                     the oracle (plan §5 WA.2; W0.4 DoD #4) -- NOT arch_expected.
 *   check           : self-checking mode for QEMU 'make check-tcg'.  Compares each
 *                     computed canonical against the baked architectural expectation
 *                     and prints "<id>\tPASS" / "<id>\tFAIL ...".  Exit non-zero on
 *                     ANY mismatch.  A self-checking tcg test legitimately uses the
 *                     architecture as its oracle; the independent oracle is the diff.
 *
 * Canonical output:
 *   reg_only    "0x%016" PRIx64
 *   flags_only  "nzcv=0x%x"   (NZCV nibble = (nzcv>>28)&0xf)
 *
 * Inputs are baked as C constants and fed via inline-asm register/memory operands
 * (same proven idiom as tools/diff/corpus_runner.c).  Build at -O0 with volatile asm
 * so nothing is folded away.  System-register tests SAVE and RESTORE the register
 * (TPIDR_EL0 is the Linux thread pointer; FPCR/FPSR are global) so the C runtime is
 * unharmed.  LSE atomics (cas/ldadd/swp) require FEAT_LSE -- run with -cpu max.
 *
 * ┌─────────────────────────────────────────────────────────────────────────────┐
 * │ STATUS: authored from the manifest; NOT YET COMPILED OR EXECUTED ON aarch64. │
 * │ It cannot be built on the x86-64 Windows dev host (no aarch64 toolchain), the │
 * │ same status as tools/diff/corpus_runner.c.  First compile is on the ARM64     │
 * │ reference / in the aarch64 guest (the lead's AMD run).  A runner defect is     │
 * │ shared by both differential sides and cancels unless translation-sensitive.   │
 * └─────────────────────────────────────────────────────────────────────────────┘
 *
 * Build:  cc -O0 -std=c11 -Wall -Wextra -o valid_corpus_runner valid_corpus_runner.c
 * Run:    ./valid_corpus_runner emit    # differential
 *         ./valid_corpus_runner check   # check-tcg self-check (exit != 0 on mismatch)
 */
#include <stdio.h>
#include <stdint.h>
#include <inttypes.h>
#include <string.h>

#if !defined(__aarch64__)
#error "valid_corpus_runner.c targets aarch64 -- build it on the ARM64 reference / in the aarch64 guest."
#endif

/* Baked architectural expectations, used ONLY in check mode (the self-checking
 * tcg oracle).  emit mode never consults these; the differential oracle is the
 * independent ARM64 reference run.  Kept in lockstep with the manifests. */
struct expect { const char *id; const char *canonical; };
static const struct expect EXPECT[] = {
    { "int_add",         "0x000000000000000c" },
    { "int_sub",         "0xfffffffffffffffc" },
    { "int_madd",        "0x0000000000000011" },
    { "int_msub",        "0x0000000000000008" },
    { "int_smulh",       "0xffffffffffffffff" },
    { "int_umulh",       "0x0000000000000001" },
    { "int_sdiv",        "0x0000000000000004" },
    { "int_adc",         "0x0000000000000031" },
    { "int_sbc",         "0x0000000000000020" },
    { "int_extr",        "0x2222222233333333" },
    { "int_ubfx",        "0x0000000000000012" },
    { "int_sxtb",        "0xffffffffffffff80" },
    { "int_uxth",        "0x000000000000ffff" },
    { "int_clz",         "0x000000000000003f" },
    { "int_rbit",        "0x8000000000000000" },
    { "int_rev",         "0x0807060504030201" },
    { "br_cbz_taken",    "0x0000000000000001" },
    { "br_cbnz_taken",   "0x0000000000000002" },
    { "br_tbz_taken",    "0x0000000000000003" },
    { "br_tbnz_taken",   "0x0000000000000004" },
    { "cc_eq",           "0x0000000000000001" },
    { "cc_ne",           "0x0000000000000001" },
    { "cc_lo",           "0x0000000000000001" },
    { "cc_ge",           "0x0000000000000001" },
    { "cc_csinc",        "0x000000000000000b" },
    { "cc_csneg",        "0xfffffffffffffff9" },
    { "exc_sdiv_zero",   "0x0000000000000000" },
    { "exc_udiv_zero",   "0x0000000000000000" },
    { "fp_fadd",         "0x4008000000000000" },
    { "fp_fsub",         "0x4000000000000000" },
    { "fp_fmul",         "0x4018000000000000" },
    { "fp_fdiv",         "0x3fe0000000000000" },
    { "fp_fsqrt",        "0x4000000000000000" },
    { "fp_fabs",         "0x4000000000000000" },
    { "fp_fneg",         "0xc000000000000000" },
    { "fp_scvtf",        "0x4014000000000000" },
    { "fp_fcvtzs",       "0x0000000000000003" },
    { "fp_fcvt_d2s",     "0x000000003fc00000" },
    { "fp_fcmp_eq",      "nzcv=0x6" },
    { "fp_fcmp_lt",      "nzcv=0x8" },
    { "simd_add2d",      "0x0000000000000003" },
    { "simd_and",        "0x00f000f000f000f0" },
    { "simd_cnt",        "0x0101010101010101" },
    { "simd_fadd2s",     "0x0000000040400000" },
    { "atom_ldxr_stxr",  "0x0000000000000101" },
    { "atom_ldaxr_stlxr","0x0000000000000201" },
    { "atom_cas",        "0x0000000000000200" },
    { "atom_ldadd",      "0x0000000000000105" },
    { "atom_swp",        "0x0000000000000999" },
    { "sys_tpidr",       "0xdeadbeefcafef00d" },
    { "sys_nzcv",        "0x00000000f0000000" },
    { "sys_fpcr",        "0x0000000007800000" },
    { "sys_fpsr",        "0x0000000000000001" },
    { "seed_negctrl",    "0x0000000000000003" },
};

static int g_check;        /* 0 = emit, 1 = check */
static int g_failures;
static int g_emitted;

static const char *expected_of(const char *id) {
    for (size_t i = 0; i < sizeof(EXPECT) / sizeof(EXPECT[0]); i++)
        if (strcmp(EXPECT[i].id, id) == 0)
            return EXPECT[i].canonical;
    return NULL;
}

static void emit_or_check(const char *id, const char *canonical) {
    g_emitted++;
    if (!g_check) {
        printf("%s\t%s\n", id, canonical);
        return;
    }
    const char *exp = expected_of(id);
    if (exp && strcmp(exp, canonical) == 0) {
        printf("%s\tPASS\n", id);
    } else {
        printf("%s\tFAIL got=%s want=%s\n", id, canonical, exp ? exp : "(unknown-id)");
        g_failures++;
    }
}

static void out_reg(const char *id, uint64_t v) {
    char b[32];
    snprintf(b, sizeof b, "0x%016" PRIx64, v);
    emit_or_check(id, b);
}
static void out_flags(const char *id, uint64_t nzcv) {
    char b[32];
    snprintf(b, sizeof b, "nzcv=0x%x", (unsigned)((nzcv >> 28) & 0xf));
    emit_or_check(id, b);
}

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "check") == 0) g_check = 1;
    else if (argc > 1 && strcmp(argv[1], "emit") != 0) {
        fprintf(stderr, "usage: %s [emit|check]\n", argv[0]);
        return 2;
    }

    /* ---------------- integer ---------------- */
    { uint64_t a = 7, b = 5, v;
      __asm__ volatile("add %0,%1,%2" : "=r"(v) : "r"(a), "r"(b)); out_reg("int_add", v); }
    { uint64_t a = 5, b = 9, v;
      __asm__ volatile("sub %0,%1,%2" : "=r"(v) : "r"(a), "r"(b)); out_reg("int_sub", v); }
    { uint64_t a = 3, b = 4, c = 5, v;
      __asm__ volatile("madd %0,%1,%2,%3" : "=r"(v) : "r"(a), "r"(b), "r"(c)); out_reg("int_madd", v); }
    { uint64_t a = 3, b = 4, c = 20, v;
      __asm__ volatile("msub %0,%1,%2,%3" : "=r"(v) : "r"(a), "r"(b), "r"(c)); out_reg("int_msub", v); }
    { uint64_t a = 0xffffffffffffffffULL, b = 2, v;      /* (-1)*2, signed high */
      __asm__ volatile("smulh %0,%1,%2" : "=r"(v) : "r"(a), "r"(b)); out_reg("int_smulh", v); }
    { uint64_t a = 0x100000000ULL, b = 0x100000000ULL, v;
      __asm__ volatile("umulh %0,%1,%2" : "=r"(v) : "r"(a), "r"(b)); out_reg("int_umulh", v); }
    { uint64_t a = 20, b = 5, v;
      __asm__ volatile("sdiv %0,%1,%2" : "=r"(v) : "r"(a), "r"(b)); out_reg("int_sdiv", v); }
    { uint64_t a = 0xffffffffffffffffULL, b = 1, c = 0x10, d = 0x20, v;   /* adds sets C=1 */
      __asm__ volatile("adds xzr,%1,%2\n\tadc %0,%3,%4"
                       : "=r"(v) : "r"(a), "r"(b), "r"(c), "r"(d) : "cc"); out_reg("int_adc", v); }
    { uint64_t a = 5, b = 3, c = 0x30, d = 0x10, v;                       /* subs sets C=1 (no borrow) */
      __asm__ volatile("subs xzr,%1,%2\n\tsbc %0,%3,%4"
                       : "=r"(v) : "r"(a), "r"(b), "r"(c), "r"(d) : "cc"); out_reg("int_sbc", v); }
    { uint64_t a = 0x1111111122222222ULL, b = 0x3333333344444444ULL, v;
      __asm__ volatile("extr %0,%1,%2,#32" : "=r"(v) : "r"(a), "r"(b)); out_reg("int_extr", v); }
    { uint64_t a = 0x1234, v;
      __asm__ volatile("ubfx %0,%1,#8,#8" : "=r"(v) : "r"(a)); out_reg("int_ubfx", v); }
    { uint32_t a = 0x80; uint64_t v;
      __asm__ volatile("sxtb %0,%w1" : "=r"(v) : "r"(a)); out_reg("int_sxtb", v); }
    { uint32_t a = 0xffff; uint64_t v = 0;
      __asm__ volatile("uxth %w0,%w1" : "=r"(v) : "r"(a)); out_reg("int_uxth", v); }
    { uint64_t a = 1, v;
      __asm__ volatile("clz %0,%1" : "=r"(v) : "r"(a)); out_reg("int_clz", v); }
    { uint64_t a = 1, v;
      __asm__ volatile("rbit %0,%1" : "=r"(v) : "r"(a)); out_reg("int_rbit", v); }
    { uint64_t a = 0x0102030405060708ULL, v;
      __asm__ volatile("rev %0,%1" : "=r"(v) : "r"(a)); out_reg("int_rev", v); }

    /* ------------- branch / exception ------------- */
    { uint64_t x1 = 0, v;
      __asm__ volatile("mov %0,#0xff\n\tcbz %1,1f\n\tmov %0,#0xee\n\tb 2f\n1:\n\tmov %0,#1\n2:\n"
                       : "=&r"(v) : "r"(x1) : "cc"); out_reg("br_cbz_taken", v); }
    { uint64_t x1 = 5, v;
      __asm__ volatile("mov %0,#0xff\n\tcbnz %1,1f\n\tmov %0,#0xee\n\tb 2f\n1:\n\tmov %0,#2\n2:\n"
                       : "=&r"(v) : "r"(x1) : "cc"); out_reg("br_cbnz_taken", v); }
    { uint64_t x1 = 4, v;   /* bit0 == 0 -> tbz taken */
      __asm__ volatile("mov %0,#0xff\n\ttbz %1,#0,1f\n\tmov %0,#0xee\n\tb 2f\n1:\n\tmov %0,#3\n2:\n"
                       : "=&r"(v) : "r"(x1) : "cc"); out_reg("br_tbz_taken", v); }
    { uint64_t x1 = 1, v;   /* bit0 == 1 -> tbnz taken */
      __asm__ volatile("mov %0,#0xff\n\ttbnz %1,#0,1f\n\tmov %0,#0xee\n\tb 2f\n1:\n\tmov %0,#4\n2:\n"
                       : "=&r"(v) : "r"(x1) : "cc"); out_reg("br_tbnz_taken", v); }
    { uint64_t a = 5, b = 5, v;
      __asm__ volatile("cmp %1,%2\n\tcset %0,eq" : "=r"(v) : "r"(a), "r"(b) : "cc"); out_reg("cc_eq", v); }
    { uint64_t a = 5, b = 6, v;
      __asm__ volatile("cmp %1,%2\n\tcset %0,ne" : "=r"(v) : "r"(a), "r"(b) : "cc"); out_reg("cc_ne", v); }
    { uint64_t a = 3, b = 5, v;
      __asm__ volatile("cmp %1,%2\n\tcset %0,lo" : "=r"(v) : "r"(a), "r"(b) : "cc"); out_reg("cc_lo", v); }
    { uint64_t a = 5, b = 3, v;
      __asm__ volatile("cmp %1,%2\n\tcset %0,ge" : "=r"(v) : "r"(a), "r"(b) : "cc"); out_reg("cc_ge", v); }
    { uint64_t a = 10, p = 1, q = 2, v;   /* EQ false -> csinc selects Xm+1 = 11 */
      __asm__ volatile("cmp %2,%3\n\tcsinc %0,%1,%1,eq"
                       : "=r"(v) : "r"(a), "r"(p), "r"(q) : "cc"); out_reg("cc_csinc", v); }
    { uint64_t a = 7, p = 1, q = 2, v;    /* EQ false -> csneg selects -Xm = -7 */
      __asm__ volatile("cmp %2,%3\n\tcsneg %0,%1,%1,eq"
                       : "=r"(v) : "r"(a), "r"(p), "r"(q) : "cc"); out_reg("cc_csneg", v); }
    { uint64_t a = 20, b = 0, v;   /* architected: sdiv by zero -> 0, no trap */
      __asm__ volatile("sdiv %0,%1,%2" : "=r"(v) : "r"(a), "r"(b)); out_reg("exc_sdiv_zero", v); }
    { uint64_t a = 20, b = 0, v;   /* architected: udiv by zero -> 0, no trap */
      __asm__ volatile("udiv %0,%1,%2" : "=r"(v) : "r"(a), "r"(b)); out_reg("exc_udiv_zero", v); }

    /* ---------------- FP / SIMD ---------------- */
    { double a = 1.0, b = 2.0, t; uint64_t v;
      __asm__ volatile("fadd %d1,%d2,%d3\n\tfmov %0,%d1" : "=r"(v), "=w"(t) : "w"(a), "w"(b)); out_reg("fp_fadd", v); }
    { double a = 5.0, b = 3.0, t; uint64_t v;
      __asm__ volatile("fsub %d1,%d2,%d3\n\tfmov %0,%d1" : "=r"(v), "=w"(t) : "w"(a), "w"(b)); out_reg("fp_fsub", v); }
    { double a = 2.0, b = 3.0, t; uint64_t v;
      __asm__ volatile("fmul %d1,%d2,%d3\n\tfmov %0,%d1" : "=r"(v), "=w"(t) : "w"(a), "w"(b)); out_reg("fp_fmul", v); }
    { double a = 1.0, b = 2.0, t; uint64_t v;
      __asm__ volatile("fdiv %d1,%d2,%d3\n\tfmov %0,%d1" : "=r"(v), "=w"(t) : "w"(a), "w"(b)); out_reg("fp_fdiv", v); }
    { double a = 4.0, t; uint64_t v;
      __asm__ volatile("fsqrt %d1,%d2\n\tfmov %0,%d1" : "=r"(v), "=w"(t) : "w"(a)); out_reg("fp_fsqrt", v); }
    { double a = -2.0, t; uint64_t v;
      __asm__ volatile("fabs %d1,%d2\n\tfmov %0,%d1" : "=r"(v), "=w"(t) : "w"(a)); out_reg("fp_fabs", v); }
    { double a = 2.0, t; uint64_t v;
      __asm__ volatile("fneg %d1,%d2\n\tfmov %0,%d1" : "=r"(v), "=w"(t) : "w"(a)); out_reg("fp_fneg", v); }
    { uint64_t a = 5, v; double t;
      __asm__ volatile("scvtf %d1,%2\n\tfmov %0,%d1" : "=r"(v), "=w"(t) : "r"(a)); out_reg("fp_scvtf", v); }
    { double a = 3.5; uint64_t v;
      __asm__ volatile("fcvtzs %0,%d1" : "=r"(v) : "w"(a)); out_reg("fp_fcvtzs", v); }
    { double a = 1.5; float t; uint32_t w;
      __asm__ volatile("fcvt %s1,%d2\n\tfmov %w0,%s1" : "=r"(w), "=w"(t) : "w"(a)); out_reg("fp_fcvt_d2s", (uint64_t)w); }
    { double a = 1.0, b = 1.0; uint64_t f;
      __asm__ volatile("fcmp %d1,%d2\n\tmrs %0,nzcv" : "=r"(f) : "w"(a), "w"(b) : "cc"); out_flags("fp_fcmp_eq", f); }
    { double a = 1.0, b = 2.0; uint64_t f;
      __asm__ volatile("fcmp %d1,%d2\n\tmrs %0,nzcv" : "=r"(f) : "w"(a), "w"(b) : "cc"); out_flags("fp_fcmp_lt", f); }
    { uint64_t v; static const uint64_t inA[2] = {1, 0}, inB[2] = {2, 0};
      __asm__ volatile("ldr q1,[%1]\n\tldr q2,[%2]\n\tadd v0.2d,v1.2d,v2.2d\n\tumov %0,v0.d[0]"
                       : "=r"(v) : "r"(inA), "r"(inB) : "v0", "v1", "v2", "memory"); out_reg("simd_add2d", v); }
    { uint64_t v; static const uint64_t inA[2] = {0xf0f0f0f0f0f0f0f0ULL, 0}, inB[2] = {0x0ff00ff00ff00ff0ULL, 0};
      __asm__ volatile("ldr q1,[%1]\n\tldr q2,[%2]\n\tand v0.16b,v1.16b,v2.16b\n\tumov %0,v0.d[0]"
                       : "=r"(v) : "r"(inA), "r"(inB) : "v0", "v1", "v2", "memory"); out_reg("simd_and", v); }
    { uint64_t v; static const uint64_t inA[1] = {0x0102040810204080ULL};
      __asm__ volatile("ldr d1,[%1]\n\tcnt v0.8b,v1.8b\n\tumov %0,v0.d[0]"
                       : "=r"(v) : "r"(inA) : "v0", "v1", "memory"); out_reg("simd_cnt", v); }
    { uint32_t w; static const uint32_t inA[4] = {0x3f800000u, 0, 0, 0}, inB[4] = {0x40000000u, 0, 0, 0}; /* 1.0f,2.0f */
      __asm__ volatile("ldr q1,[%1]\n\tldr q2,[%2]\n\tfadd v0.2s,v1.2s,v2.2s\n\tumov %w0,v0.s[0]"
                       : "=r"(w) : "r"(inA), "r"(inB) : "v0", "v1", "v2", "memory"); out_reg("simd_fadd2s", (uint64_t)w); }

    /* ------------- atomics / exclusives -------------
       Single-threaded value semantics only; multi-thread ordering is WA.3 litmus. */
    { uint64_t mem = 0x100, ld, st, v;
      __asm__ volatile("ldxr %0,[%3]\n\tadd %0,%0,#1\n\tstxr %w1,%0,[%3]\n\tldr %2,[%3]"
                       : "=&r"(ld), "=&r"(st), "=&r"(v) : "r"(&mem) : "memory"); out_reg("atom_ldxr_stxr", v); }
    { uint64_t mem = 0x200, ld, st, v;
      __asm__ volatile("ldaxr %0,[%3]\n\tadd %0,%0,#1\n\tstlxr %w1,%0,[%3]\n\tldr %2,[%3]"
                       : "=&r"(ld), "=&r"(st), "=&r"(v) : "r"(&mem) : "memory"); out_reg("atom_ldaxr_stlxr", v); }
    { uint64_t mem = 0x100, xs = 0x100, xt = 0x200, v;   /* FEAT_LSE */
      __asm__ volatile("cas %0,%2,[%3]\n\tldr %1,[%3]"
                       : "+r"(xs), "=&r"(v) : "r"(xt), "r"(&mem) : "memory"); out_reg("atom_cas", v); }
    { uint64_t mem = 0x100, xs = 5, xt, v;               /* FEAT_LSE */
      __asm__ volatile("ldadd %2,%0,[%3]\n\tldr %1,[%3]"
                       : "=&r"(xt), "=&r"(v) : "r"(xs), "r"(&mem) : "memory"); out_reg("atom_ldadd", v); }
    { uint64_t mem = 0x100, xs = 0x999, xt, v;           /* FEAT_LSE */
      __asm__ volatile("swp %2,%0,[%3]\n\tldr %1,[%3]"
                       : "=&r"(xt), "=&r"(v) : "r"(xs), "r"(&mem) : "memory"); out_reg("atom_swp", v); }

    /* ------------- architected system registers -------------
       Each SAVES the prior value and RESTORES it so the C runtime is unharmed. */
    { uint64_t testval = 0xdeadbeefcafef00dULL, old, v;
      __asm__ volatile("mrs %1,tpidr_el0\n\tmsr tpidr_el0,%2\n\tmrs %0,tpidr_el0\n\tmsr tpidr_el0,%1"
                       : "=&r"(v), "=&r"(old) : "r"(testval) : "memory"); out_reg("sys_tpidr", v); }
    { uint64_t tv, v;
      __asm__ volatile("movz %1,#0xf000,lsl#16\n\tmsr nzcv,%1\n\tmrs %0,nzcv"
                       : "=r"(v), "=&r"(tv) : : "cc"); out_reg("sys_nzcv", v); }
    { uint64_t tv, v, old, mask;
      __asm__ volatile("mrs %2,fpcr\n\t"
                       "movz %1,#0x0780,lsl#16\n\tmsr fpcr,%1\n\t"   /* AHP|DN|FZ|RMode=10 = 0x07800000 */
                       "mrs %0,fpcr\n\t"
                       "msr fpcr,%2\n\t"                              /* restore */
                       "movz %3,#0x07c0,lsl#16\n\tand %0,%0,%3"      /* mask to architected bits */
                       : "=&r"(v), "=&r"(tv), "=&r"(old), "=&r"(mask) : : "memory"); out_reg("sys_fpcr", v); }
    { uint64_t tv, v, old, mask;
      __asm__ volatile("mrs %2,fpsr\n\t"
                       "msr fpsr,xzr\n\t"                             /* clear cumulative flags */
                       "movz %1,#1\n\tmsr fpsr,%1\n\t"                /* set IOC */
                       "mrs %0,fpsr\n\t"
                       "msr fpsr,%2\n\t"                              /* restore */
                       "movz %3,#0x9f\n\tand %0,%0,%3"               /* mask to cumulative-flag bits */
                       : "=&r"(v), "=&r"(tv), "=&r"(old), "=&r"(mask) : : "memory"); out_reg("sys_fpsr", v); }

    /* ------------- negative control -------------
       Architecturally identical to (1+2)=3.  emit mode prints the TRUE value; the
       single-bit seed mutation is injected downstream by collect_results.py --seed on
       the SUT side only.  check mode expects the true value, so it PASSES here. */
    { uint64_t a = 1, b = 2, v;
      __asm__ volatile("add %0,%1,%2" : "=r"(v) : "r"(a), "r"(b)); out_reg("seed_negctrl", v); }

    if (g_check) {
        fprintf(stderr, "valid-tcg check: %d tests, %d failure(s)\n", g_emitted, g_failures);
        return g_failures ? 1 : 0;
    }
    return 0;
}
