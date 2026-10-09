# Research background

Mihir Bellare, Ran Canetti and Hugo Krawczyk's [Keying Hash Functions for Message Authentication](https://cseweb.ucsd.edu/~mihir/papers/kmd5.pdf), CRYPTO 1996, introduces and analyzes HMAC under assumptions about the underlying hash function. It provides background for using an established keyed authentication construction rather than designing a new one.

The [selected Standard Webhooks verifier](https://github.com/standard-webhooks/standard-webhooks/blob/dc4aed97b92dd04afc6c62428fe936bae7251b6b/libraries/python/standardwebhooks/webhooks.py) uses Python's HMAC-SHA256 and constant-time digest comparison. It binds the message ID, delivery timestamp and raw body; its timestamp policy is separate from durable duplicate handling. The [specification](https://github.com/standard-webhooks/standard-webhooks/blob/7537d2a2d3d52d8f2e0ecd12527af4a9307fd81b/spec/standard-webhooks.md) explains these protocol roles.

This paper is cryptographic background. It does not prove the inbox application's transport handling, replay policy, persistence, deployment or end-to-end security. Those properties require separately reported implementation checks. No cryptographic proof or paper benchmark is reproduced here.
