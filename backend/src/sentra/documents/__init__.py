"""The document registry: what the corpus consists of.

Qdrant holds what has been indexed. That is not the same question, and the gap
between the two is what #140 measured — 17 documents indexed with no file
behind them, found by diffing two lists by hand because nothing in the system
compared them.
"""
