# Changelog

## [1.3.0](https://github.com/marcel-breuer/fidus/compare/v1.2.0...v1.3.0) (2026-11-24)


### Features

* add per-user limits and memo recovery ([7b3df89](https://github.com/marcel-breuer/fidus/commit/7b3df8971799b1b11bbde949ee5d68334908f8ea))
* **admin:** add audit views and shared invitations ([1d14ee2](https://github.com/marcel-breuer/fidus/commit/1d14ee2f30b4780f67bc57e7160c6bd429ffda3f))
* **admin:** audit views, paginated users and cross-admin invitations ([7e2538f](https://github.com/marcel-breuer/fidus/commit/7e2538f5d170dc0edf771b9e0072e00f7d61cb56))
* **chat:** add cached speech and voice dictation ([cdb4680](https://github.com/marcel-breuer/fidus/commit/cdb4680c0a7015d32d9a0a14d130f0478462a3cd))
* **chat:** add message attachments and action follow-up ([0bdef49](https://github.com/marcel-breuer/fidus/commit/0bdef4957fa3f52cdf044727b9d3544735cb38d4))
* **chat:** cached read-aloud and voice dictation ([bba937c](https://github.com/marcel-breuer/fidus/commit/bba937c0a72a25d43962ecc5c534f09d4cd05f99))
* **chat:** message attachments and follow-up after agent decisions ([9f830ae](https://github.com/marcel-breuer/fidus/commit/9f830ae9eb4df7ac2efb210327ad7db938af3388))
* **mcp:** add OAuth 2.1 authorization ([aebc60b](https://github.com/marcel-breuer/fidus/commit/aebc60b9b2407a27fe0e9757eeaa9e5e73295e6e))
* **mcp:** expose scoped file tools and resources ([9f93770](https://github.com/marcel-breuer/fidus/commit/9f937705b19274d29d8feffcae3f4035ba9c82f7))
* **mcp:** OAuth 2.1 authorization for MCP clients ([9da3f0c](https://github.com/marcel-breuer/fidus/commit/9da3f0c68eceb83f95ef4f6b056cb3a74f55ec27))
* **mcp:** scoped file tools and resources ([cb5f907](https://github.com/marcel-breuer/fidus/commit/cb5f907fbcb9077cfa1f5cdd4a0383740afb4cf9))
* per-user rate limits and recovery of stuck memos ([9a92e34](https://github.com/marcel-breuer/fidus/commit/9a92e3443f3219ae1a59f2b8e7f97e649acc930f))


### Bug Fixes

* **audio:** restart the recovery timeout when a stale memo is requeued ([7abb09a](https://github.com/marcel-breuer/fidus/commit/7abb09a1e0e7aa23b8e3fadc8c5f32765a7994f8))
* **chat:** apply per-user limits to attachment uploads and action follow-ups ([d3fa73f](https://github.com/marcel-breuer/fidus/commit/d3fa73ffd754a297d642fcf6a9d711db2fe7e839))
* **compose:** derive the backend image name from the project name ([e0b60ba](https://github.com/marcel-breuer/fidus/commit/e0b60bad2423f649e14ebba853609190a31b81fd))
* **compose:** derive the backend image name from the project name ([f4a816d](https://github.com/marcel-breuer/fidus/commit/f4a816dc74431d69a327b22cc95f7b2da719518b)), closes [#49](https://github.com/marcel-breuer/fidus/issues/49)
* **ui:** harden mobile glass accessibility ([896abb0](https://github.com/marcel-breuer/fidus/commit/896abb03498a394f7bf538fcfb08573b75610a1d))
* **ui:** mobile layout, contrast fallbacks and focus handling ([52f5ff2](https://github.com/marcel-breuer/fidus/commit/52f5ff2a93727b8f8f83b824c0967c9b0929fdfc))


### Documentation

* record MCP file tools in the audit and tool sections ([18c278f](https://github.com/marcel-breuer/fidus/commit/18c278f784b0831c22fa6bee5612230e8dfd71c5))

## [1.2.0](https://github.com/marcel-breuer/fidus/compare/v1.1.0...v1.2.0) (2026-11-23)


### Features

* **admin:** user management and runtime registration mode ([dec2b7d](https://github.com/marcel-breuer/fidus/commit/dec2b7dfa1adad26df07bd893693680c9808ed05))
* **admin:** user management and runtime registration mode ([7dbcca8](https://github.com/marcel-breuer/fidus/commit/7dbcca8893682548212125beda7a862c78b03b18)), closes [#35](https://github.com/marcel-breuer/fidus/issues/35)
* **api:** add personal access tokens and MCP server ([1a68b8a](https://github.com/marcel-breuer/fidus/commit/1a68b8a90c8ef2cee58cb9cebe6ba17c3ffa4d19)), closes [#22](https://github.com/marcel-breuer/fidus/issues/22)
* **audio:** voice memos with transcription and read-aloud ([973753f](https://github.com/marcel-breuer/fidus/commit/973753f72534a26f8e314a44783793ad039ebb81))
* **audio:** voice memos with worker transcription and read-aloud ([a91a5b3](https://github.com/marcel-breuer/fidus/commit/a91a5b35d3a31040a28283796d91012e88594faa))
* **chat:** durable memories, web search, citations and confirmed agent tools ([bedded3](https://github.com/marcel-breuer/fidus/commit/bedded338b2bc9b926166cb764a23920a6dbf93f)), closes [#18](https://github.com/marcel-breuer/fidus/issues/18)
* **chat:** let the agent create and update text files ([d094994](https://github.com/marcel-breuer/fidus/commit/d094994e17852b351de56e3ded67dbf30dda222a))
* **chat:** let the agent create and update text files ([fe6d0b0](https://github.com/marcel-breuer/fidus/commit/fe6d0b00e5239bb92f4a2b6d6371729275f157a0))
* **chat:** memories, web search, citations and confirmed agent tools ([b678223](https://github.com/marcel-breuer/fidus/commit/b678223c152fa4233d26b39063eb2c5cc295f26c))
* personal access tokens and MCP server ([182d452](https://github.com/marcel-breuer/fidus/commit/182d452617d4b743e2b13266bd5b641417808fcb))
* usage counters, backup and restore, structured logs and security review ([69e3d8c](https://github.com/marcel-breuer/fidus/commit/69e3d8c10a93e710212e07ab7fdc6254a11ac97d))
* usage counters, backup and restore, structured logs and security review ([e6e0870](https://github.com/marcel-breuer/fidus/commit/e6e0870c0a35fb319e6c270231a1ec2e71982113)), closes [#23](https://github.com/marcel-breuer/fidus/issues/23)
* **web:** add access token settings page ([66141ad](https://github.com/marcel-breuer/fidus/commit/66141adca6a2027335ffc41a6866866f0e72c807)), closes [#22](https://github.com/marcel-breuer/fidus/issues/22)
* **web:** offer audio scopes for access tokens ([c7217a8](https://github.com/marcel-breuer/fidus/commit/c7217a8c86dd81459cd1da8b5511f63762ee863d))

## [1.1.0](https://github.com/marcel-breuer/fidus/compare/v1.0.1...v1.1.0) (2026-11-23)


### Features

* add Compose stack, gateway, CI and docs for the scaffold ([9772d4c](https://github.com/marcel-breuer/fidus/commit/9772d4c07c1219c8ede8ae31e8740ed068788254)), closes [#5](https://github.com/marcel-breuer/fidus/issues/5)
* **admin:** module settings and invitation management ([e550c37](https://github.com/marcel-breuer/fidus/commit/e550c375248fc2787eb71bd76e5505fc6579f353))
* **admin:** module settings and invitation management ([b2c2e26](https://github.com/marcel-breuer/fidus/commit/b2c2e26586963adf9c7fb5e8bfa7b54ff12dc85b))
* **auth:** add double-submit CSRF token for cookie sessions ([ae22efa](https://github.com/marcel-breuer/fidus/commit/ae22efabb0cc7cf45c76ded0231da570e9e0c632))
* **auth:** add double-submit CSRF token for cookie sessions ([0b73cac](https://github.com/marcel-breuer/fidus/commit/0b73cac01f77a5e7c2c7e553ebb770c9d61dd14a))
* **auth:** invitations for invite-only registration ([b626a15](https://github.com/marcel-breuer/fidus/commit/b626a15d2a852bbb108265696c6580d9482ca9d4))
* **auth:** invitations for invite-only registration ([0369e6f](https://github.com/marcel-breuer/fidus/commit/0369e6f5dd9596be88f59b4896f63b5f179122c2))
* **auth:** rate limit login and registration ([8507636](https://github.com/marcel-breuer/fidus/commit/85076361c94e15c14cb24c0e90a5265447a46f52))
* **auth:** rate limit login and registration ([c36580c](https://github.com/marcel-breuer/fidus/commit/c36580cfd5b64a25bde78e34eccaaa36bbe9b412))
* **auth:** schedule session purge and add sign out everywhere ([dc9073c](https://github.com/marcel-breuer/fidus/commit/dc9073c0116cf0767bfd50274885a9871add1027))
* **auth:** schedule session purge and add sign out everywhere ([2131b02](https://github.com/marcel-breuer/fidus/commit/2131b0265c087d209e1b01a94228736afc1f1cde))
* **auth:** server-side revocable sessions ([b73188f](https://github.com/marcel-breuer/fidus/commit/b73188f1fe106c8b4fc644dff5f23627f6cfd058))
* **auth:** server-side revocable sessions ([079c270](https://github.com/marcel-breuer/fidus/commit/079c2708327618bef3cf4763767e7299b89276c9))
* **backend:** add API, auth, row-level security, module registry and worker ([fbb330e](https://github.com/marcel-breuer/fidus/commit/fbb330e3a6826ca67eb8df676469610107258f67))
* **chat:** model config, provider interface, conversations and message history ([e821ff2](https://github.com/marcel-breuer/fidus/commit/e821ff2028daf83fc86de28052f2613ba525abbf))
* **chat:** model config, provider interface, conversations and message history ([08717a5](https://github.com/marcel-breuer/fidus/commit/08717a5512e735ba3785d34103ff1b1f17cf3a02))
* **chat:** streaming chat endpoint and chat screen ([c496562](https://github.com/marcel-breuer/fidus/commit/c4965626fd40837dbfbd1f8d3a442f8c02f24d02))
* **chat:** streaming chat endpoint and chat screen ([d22c1e1](https://github.com/marcel-breuer/fidus/commit/d22c1e14e95f86dc7a3d26b654f4bdbe01e243ec))
* **files:** storage, upload, folders, versions and file browser ([0856ce6](https://github.com/marcel-breuer/fidus/commit/0856ce61967412e364c3f5a81a55f49a2df2d19a))
* **files:** storage, upload, folders, versions and file browser ([b242e72](https://github.com/marcel-breuer/fidus/commit/b242e722118c21ccb607fc60a068350089647236))
* **files:** text extraction, embeddings and hybrid retrieval ([48f61a5](https://github.com/marcel-breuer/fidus/commit/48f61a563fd954afa649555cf764548ff165c3f9))
* **files:** text extraction, embeddings and hybrid retrieval ([4acfb3e](https://github.com/marcel-breuer/fidus/commit/4acfb3e3b10d48af485778971407d2b71191cdc6))
* **frontend:** add SvelteKit shell with i18n, auth pages and module sidebar ([c460eea](https://github.com/marcel-breuer/fidus/commit/c460eea7fcca66b4c342070e8b7bbed24fd511bb)), closes [#5](https://github.com/marcel-breuer/fidus/issues/5)
* **frontend:** apply glass design ([1ce48e0](https://github.com/marcel-breuer/fidus/commit/1ce48e06e56d49981b56a1adc609f6bf774a3bd8))
* **frontend:** apply glass design with #A4DDF5 as primary color ([2658d31](https://github.com/marcel-breuer/fidus/commit/2658d31742e08749bbf4c503fdce77e7bbfb2cb6))
* **frontend:** generate API types from the OpenAPI schema ([7425543](https://github.com/marcel-breuer/fidus/commit/7425543c25923e265c0def5629d528694bf83cde))
* **frontend:** generate API types from the OpenAPI schema ([38bc1bf](https://github.com/marcel-breuer/fidus/commit/38bc1bf10f5b5ab90109a8c4ce0bf76e93a0bc83))
* **frontend:** use a typed openapi-fetch client for all API calls ([b77bd2a](https://github.com/marcel-breuer/fidus/commit/b77bd2a4f31186274f1f1fd22c925357f2434ec0))
* **frontend:** use a typed openapi-fetch client for all API calls ([2e6489e](https://github.com/marcel-breuer/fidus/commit/2e6489ef9270bb7e14a57e55cab62728961b45da))
* **gateway:** configurable trusted proxies for the client address ([e021d7d](https://github.com/marcel-breuer/fidus/commit/e021d7d5d68a8291a1a13fc3cc8003845facfcb8))
* **gateway:** configurable trusted proxies for the client address ([d1f175f](https://github.com/marcel-breuer/fidus/commit/d1f175fb6c2132d1707dd5a4f1085abe4bf43598))
* project scaffold ([ab256c5](https://github.com/marcel-breuer/fidus/commit/ab256c5e78fc7485a4c60716ba57d9a78e1358fb))
* **tasks:** tasks module with in-app reminders ([ce30ffb](https://github.com/marcel-breuer/fidus/commit/ce30ffbde6d80750e20a0b10643726e4c67ab951))
* **tasks:** tasks module with in-app reminders ([8d0703f](https://github.com/marcel-breuer/fidus/commit/8d0703f12063544452e98020d6577259990a7750))
* **worker:** add heartbeat-based liveness healthcheck ([3557ca5](https://github.com/marcel-breuer/fidus/commit/3557ca5fb29a473901f1b2e98d82bb19ce45f7db))
* **worker:** heartbeat-based liveness healthcheck ([d831e67](https://github.com/marcel-breuer/fidus/commit/d831e677051ea6e5bc2df78518d259e67acb52bc))


### Bug Fixes

* **api:** regenerate API types after the schema export ([a9bc3ef](https://github.com/marcel-breuer/fidus/commit/a9bc3ef071d9f85740dbac9dd745c93dbd20c445))
* **tests:** use a test-specific application role ([89142d5](https://github.com/marcel-breuer/fidus/commit/89142d5d0a8cb44ed50e106c433162de9486db05))
* **tests:** use a test-specific application role ([d60f63d](https://github.com/marcel-breuer/fidus/commit/d60f63d844cf1148a1b1acff138902560c89a9d0))

## [1.0.1](https://github.com/marcel-breuer/fidus/compare/v1.0.0...v1.0.1) (2026-11-23)


### Bug Fixes

* use plain v-prefixed release tags without package name ([8a6bc28](https://github.com/marcel-breuer/fidus/commit/8a6bc281031635fd79679d48b427722c5281b865))
* use plain v-prefixed release tags without package name ([8e32083](https://github.com/marcel-breuer/fidus/commit/8e32083daf272249aee6f02ed107cffeb5c37dc3))


### Documentation

* add architecture overview, API/MCP rules and skill ([b5ea260](https://github.com/marcel-breuer/fidus/commit/b5ea260c96122448315e21bde26ca45f7d2a23c9))
* add repository rules, agent skills, contributing guide and README ([1f3cba0](https://github.com/marcel-breuer/fidus/commit/1f3cba0a8149696523ffd0b282ae37f58bfa7a29))
* add specification and repository guidelines ([7653cf6](https://github.com/marcel-breuer/fidus/commit/7653cf66b3e93f44af9a4e032fa65e14cd944809))
* record architecture decisions ([5867e9a](https://github.com/marcel-breuer/fidus/commit/5867e9a1f389c4e3e63be7ff57712865f72188c5))
* record architecture decisions for gateway, queue, frontend, RLS and registration ([367fe3c](https://github.com/marcel-breuer/fidus/commit/367fe3c804bdbf8387ccd397d79b929b1a3e51b8))

## 1.0.0 (2026-11-23)


### Documentation

* add architecture overview, API/MCP rules and skill ([b5ea260](https://github.com/marcel-breuer/fidus/commit/b5ea260c96122448315e21bde26ca45f7d2a23c9))
* add repository rules, agent skills, contributing guide and README ([1f3cba0](https://github.com/marcel-breuer/fidus/commit/1f3cba0a8149696523ffd0b282ae37f58bfa7a29))
* add specification and repository guidelines ([7653cf6](https://github.com/marcel-breuer/fidus/commit/7653cf66b3e93f44af9a4e032fa65e14cd944809))
* record architecture decisions ([5867e9a](https://github.com/marcel-breuer/fidus/commit/5867e9a1f389c4e3e63be7ff57712865f72188c5))
* record architecture decisions for gateway, queue, frontend, RLS and registration ([367fe3c](https://github.com/marcel-breuer/fidus/commit/367fe3c804bdbf8387ccd397d79b929b1a3e51b8))
