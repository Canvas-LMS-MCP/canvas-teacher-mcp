// L2 java-junit TEMPLATE test scaffold — 4 tag groups (T1..T4), each holding MANY @Test items.
// classroom.yml runs each group as one grader: --include-tag T1 .. T4 (20 pts each).
//
// Per assignment: keep the @Tag groups, replace every placeholder with real items.
// A common layout: T1 = basic cases · T2 = boundary/edge · T3 = core logic · T4 = algorithm or
// source constraints.
//
// RULES (see git-asmt-repo/languages/java-junit.md):
//  - Function test  -> call the method, assert its RETURN value (or the state it mutated).
//  - Output test    -> capture stdout with out(), assert VALUES case-insensitively as substrings.
//                      Never assert whole lines, whitespace, or a label the instruction never required.
//  - Source check   -> use code(), NOT src(): the starter's own comments contain the forbidden name,
//                      and a raw src() check fails correct students (A61/A67, 2026-07-30).
//  - A group is NOT one test: add as many items per group as the problem needs, so every
//    case the spec implies is exercised. But only test edges the INSTRUCTION states —
//    an unstated case (e.g. negatives when the spec never allows them) is a trap; fix the
//    instruction first, then test it (L1 §3).
//  - The placeholders below FAIL on purpose. A placeholder that passes is a silent hole (L1 GATE A).
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Tag;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Paths;

public class MainTest {

    /** Run Main.main and capture what it printed. */
    static String out(String... args) {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        PrintStream orig = System.out;
        System.setOut(new PrintStream(buf));
        try {
            Main.main(args);
        } finally {
            System.setOut(orig);
        }
        return buf.toString().trim();
    }

    /** Feed stdin before calling out(...) when the program reads input. */
    static void stdin(String text) {
        System.setIn(new ByteArrayInputStream(text.getBytes()));
    }

    /** The student's source, raw. Use code() for any forbidden/required-token check. */
    static String src() {
        try { return new String(Files.readAllBytes(Paths.get("src/Main.java"))); }
        catch (Exception e) { return ""; }
    }

    /** Source with comments removed — the only thing a source check may look at. */
    static String code() {
        return src().replaceAll("(?s)/\\*.*?\\*/", " ")
                    .replaceAll("(?m)//.*$", " ");
    }

    // ---- Group T1 ----
    @Test @Tag("T1")
    public void t1_placeholder() {
        fail("TODO: replace with real T1 items for this assignment");
    }

    // ---- Group T2 ----
    @Test @Tag("T2")
    public void t2_placeholder() {
        fail("TODO: replace with real T2 items for this assignment");
    }

    // ---- Group T3 ----
    @Test @Tag("T3")
    public void t3_placeholder() {
        fail("TODO: replace with real T3 items for this assignment");
    }

    // ---- Group T4 ----
    @Test @Tag("T4")
    public void t4_placeholder() {
        fail("TODO: replace with real T4 items for this assignment");
    }
}
