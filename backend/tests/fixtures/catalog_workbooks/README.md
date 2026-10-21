# Catalog workbook security fixtures

Task 7 builds malicious ZIP/OOXML fixtures in memory so that no executable,
macro-enabled, encrypted, or decompression-bomb artifact is persisted in the
repository.  The unit fixtures cover path and Unicode collisions, member-count
ordering, relationship/part allowlists, DTD/entities, formulas, hidden content,
merged cells, and byte/ratio capacity gates.  Integration fixtures must use
runner-owned disposable storage and databases only.
