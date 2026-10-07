"""Pins v04_mf_05: tokenize -> normalize -> count pipeline composition."""
from src.v04.mf05.tokenize import tokenize
from src.v04.mf05.normalize import normalize
from src.v04.mf05.count import word_counts

toks = tokenize("Hello hello  WORLD\n")
assert toks == ["Hello", "hello", "WORLD"], toks
norm = normalize(toks)
assert norm == ["hello", "hello", "world"], norm
assert word_counts(norm) == {"hello": 2, "world": 1}
assert normalize(["  ", "\t"]) == []
print("EVAL_PASSED")
