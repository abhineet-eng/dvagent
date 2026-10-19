"""Fast unit tests: reply parsing, mutation rules, coverage parsing, edit application."""
from dvagent.agent import apply_edits
from dvagent.coverage import parse_coverage_dat
from dvagent.extract import extract_json, extract_python, number_lines
from dvagent.mutate import _bump_number, candidates


def test_extract_python_picks_cocotb_block():
    reply = "Plan...\n```python\nprint('x')\n```\nand\n```python\nimport cocotb\n\n@cocotb.test()\nasync def t(dut):\n    pass\n```"
    code = extract_python(reply)
    assert code.startswith("import cocotb") and "async def t" in code


def test_extract_python_unterminated_fence():
    reply = "```python\nimport cocotb\n@cocotb.test()\nasync def t(dut):\n    pass\n"
    assert "async def t" in extract_python(reply)


def test_extract_python_none():
    assert extract_python("I think the design is wrong.") is None


def test_extract_json_variants():
    assert extract_json('```json\n{"blame": "design"}\n```')["blame"] == "design"
    assert extract_json('Answer: {"bug_line": 12, "fix": [{"line": 12, "new_text": "a <= b;"}],}')["bug_line"] == 12
    assert extract_json('text {"a": "brace } inside"} more')["a"] == "brace } inside"
    assert extract_json("no json here") is None


def test_number_lines():
    assert number_lines("a\nb") == "1 | a\n2 | b"


SRC = """module m (input clk, input [3:0] a, output reg [3:0] q, output wire f);
    wire [4:0] s = a + 4'd3;
    always @(posedge clk) begin
        if (a < 4'd9) q <= s[3:0];
        else q <= -a;
    end
    assign f = (q == 4'd0) && !a[0];
endmodule"""


def test_mutation_rules():
    muts = candidates(SRC)
    texts = [m.mutated for m in muts]
    # the non-blocking assignment '<=' is never turned into a comparison
    assert not any("q < s" in t or "q >= s" in t for t in texts)
    # relational '<' inside the condition is mutated
    assert any("a <= 4'd9" in t for t in texts)
    # unary minus is left alone, binary plus is swapped
    assert not any("q <= +a" in t for t in texts)
    assert any("a - 4'd3" in t for t in texts)
    # constants are bumped by one, conditions inverted, statements deleted
    assert any("4'd10" in t for t in texts) and any("4'd8" in t for t in texts)
    assert any("!(a < 4'd9)" in t for t in texts)
    assert any(m.operator == "deleted" for m in muts)
    assert any("a[0]" in t and "!a[0]" not in t and "f =" in t for t in texts)
    # every mutant changes exactly one line and can be applied
    for m in muts:
        out = m.apply(SRC)
        assert sum(x != y for x, y in zip(out.split("\n"), SRC.split("\n"))) == 1


def test_bump_number():
    assert _bump_number("8'hFF", 1) is None
    assert _bump_number("8'hFF", -1) == "8'hFE"
    assert _bump_number("4'b0001", 1) == "4'b0010"
    assert _bump_number("16'sh7FFF", 1) == "16'sh8000"
    assert _bump_number("0", -1) is None
    assert _bump_number("7", 1) == "8"


def test_apply_edits():
    text = "a\n    q <= x | y;\nc"
    assert apply_edits(text, [{"line": 1, "new_text": "B"}])[0] == "B\n    q <= x | y;\nc"
    # a wrong line number is corrected by the line's current text; indentation is kept
    patched, lines, _ = apply_edits(text, [{"line": 9, "old_text": "q <= x | y;", "new_text": "q <= x ^ y;"}])
    assert patched == "a\n    q <= x ^ y;\nc" and lines == [2]
    assert apply_edits(text, [{"line": 9, "new_text": "x"}])[0] is None
    assert apply_edits(text, [{"line": 1, "new_text": "x\ny"}])[0] is None
    assert apply_edits(text, [{"line": 2, "old_text": "nope", "new_text": "x"}])[0] is None
    assert apply_edits(text, [{"oops": 1}])[0] is None


def test_parse_coverage_dat(tmp_path):
    f = tmp_path / "coverage.dat"
    def entry(line, page, o, n, count):
        keys = f"\x01f\x02{tmp_path}/m.v\x01l\x02{line}\x01n\x02{n}\x01page\x02{page}/m\x01o\x02{o}"
        return f"C '{keys}' {count}\n"
    f.write_text("# SystemC::Coverage-3\n" + entry(2, "v_line", "block", 1, 5) + entry(4, "v_branch", "if", 2, 3)
                 + entry(4, "v_branch", "else", 3, 0) + entry(7, "v_toggle", "toggle", 4, 0))
    (tmp_path / "m.v").write_text("module m;\n  always\n\n  if (a) x = 1; else x = 0;\nendmodule\n")
    cov = parse_coverage_dat(f)
    assert (cov.hit, cov.total) == (2, 3)
    assert "line 4" in cov.describe_missed() and "else" in cov.describe_missed()
