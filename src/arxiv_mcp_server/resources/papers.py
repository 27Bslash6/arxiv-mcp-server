"""Resource management and storage for arXiv papers.

NOTE: PaperManager was removed — it was dead code never imported by server.py,
and its top-level pymupdf4llm + arxiv imports added ~150MB to baseline RSS.
Paper operations are handled by tools/download.py and tools/list_papers.py.
"""
