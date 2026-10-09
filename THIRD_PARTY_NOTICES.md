# Third-party notices

The receiver, storage, CLI, product tests, and documentation are reused from the
existing local inbox candidate under the MIT license in `LICENSE`.
Standard Webhooks 1.1.0, commit
`dc4aed97b92dd04afc6c62428fe936bae7251b6b`, is copied into
`signed_webhook_inbox._vendor.standardwebhooks` as an executable component.
Its verifier, initializer, exception re-export, and typing marker preserve the upstream bytes; its
MIT license is included beside them and reproduced below. A raw source snapshot,
unchanged tests, package metadata, and README are retained under `upstream/`.
Svix receiver patterns were previously inspected; no bridge or separate Svix SDK
implementation is copied into the inbox extension.
The Standard Webhooks specification is Apache-2.0 and remains at the linked
upstream source in [RESEARCH.md](RESEARCH.md).

## standardwebhooks 1.1.0

The MIT License

Copyright (c) 2023 Svix (https://www.svix.com)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
