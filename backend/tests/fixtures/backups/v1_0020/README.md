# Synthetic encrypted v1 / schema 0020 reader fixture

This fixture contains no production data or secret. It freezes the backup v1
wire format for schema revision `0020`, using the public test-only AES key in
`test-keyring.json`. The two `.enc` files are base64-armored ciphertext so Git
can store them as strict UTF-8; tests decode the armor before invoking the
current backup reader.

Generation provenance:

- historical schema target: `0020`
- repository baseline: `1ead0fd952d0aba45ad2bc39fc744c1967f8d587`
- key ID: `synthetic-v1-0020-test`
- generator: independent AES-256-GCM framing script implementing the published
  `CLSEN-BACKUP-AESGCM-1` format (it does not import the current writer)
- plaintext: a synthetic manifest and a minimal historical-schema SQL marker;
  neither contains user, order, SKU, title, comment, or credential data

`sha256sums.json` freezes plaintext and decoded-ciphertext digests. The canonical
runner separately creates and fully restores a current-head backup against a
new runner-owned `clsen_restore_<uuid>` database.
