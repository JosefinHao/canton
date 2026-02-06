# Splice Scan API Client - API Reference

This document provides a reference of all available endpoints in the `SpliceScanClient` Python library, organized by functional area.

## Table of Contents

- [DSO Queries](#dso-queries)
- [Validator Queries](#validator-queries)
- [Scan Configuration Queries](#scan-configuration-queries)
- [Update History Queries](#update-history-queries)
- [State/ACS Queries](#stateacs-queries)
- [Holdings Queries](#holdings-queries)
- [ANS (Amulet Name Service) Queries](#ans-amulet-name-service-queries)
- [Mining Rounds Queries](#mining-rounds-queries)
- [Transfer Queries](#transfer-queries)
- [Event Queries](#event-queries)
- [Domain/Synchronizer Queries](#domainsynchronizer-queries)
- [Migration Queries](#migration-queries)
- [Backfilling Queries](#backfilling-queries)
- [Featured Apps Queries](#featured-apps-queries)
- [Amulet Rules Queries](#amulet-rules-queries)
- [Vote Queries](#vote-queries)
- [Network Information](#network-information)
- [Health/Status Endpoints](#healthstatus-endpoints)

---

## DSO Queries

### `get_dso()`
**Endpoint:** `GET /v0/dso`
**Description:** Get DSO information including sv_user, sv_party_id, dso_party_id, voting_threshold, latest_mining_round, amulet_rules, dso_rules, sv_node_states, and initial_round.

### `get_dso_party_id()`
**Endpoint:** `GET /v0/dso-party-id`
**Description:** Get the party ID of the DSO for the Splice network.

---

## Validator Queries

### `get_validator_faucets(validator_ids)`
**Endpoint:** `GET /v0/validators/validator-faucets`
**Parameters:**
- `validator_ids` (List[str]): A list of validator party IDs

**Description:** Get validator liveness statistics. For every argument that is a valid onboarded validator, return statistics on its liveness activity according to on-ledger state.

### `get_validator_licenses(after=None, limit=1000)`
**Endpoint:** `GET /v0/admin/validator/licenses`
**Parameters:**
- `after` (Optional[int]): A next_page_token from a prior response; if absent, return the first page
- `limit` (int): Maximum number of elements to return (default: 1000)

**Description:** List all validators currently approved by members of the DSO, paginated, sorted newest-first.

### `get_top_validators_by_validator_faucets(limit)`
**Endpoint:** `GET /v0/top-validators-by-validator-faucets`
**Parameters:**
- `limit` (int): Maximum number of validator records that may be returned

**Description:** Get a list of top validators by number of rounds in which they collected faucets.

---

## Scan Configuration Queries

### `get_scans()`
**Endpoint:** `GET /v0/scans`
**Description:** Retrieve Canton scan configuration for all SVs, grouped by connected synchronizer ID.

### `get_dso_sequencers()`
**Endpoint:** `GET /v0/dso-sequencers`
**Description:** Retrieve Canton sequencer configuration for all SVs, grouped by connected synchronizer ID.

### `get_sv_bft_sequencers()`
**Endpoint:** `GET /v0/sv-bft-sequencers`
**Description:** Retrieve Canton BFT sequencer configuration for this SV (internal endpoint).

### `get_amulet_price_votes()`
**Endpoint:** `GET /v0/amulet-price/votes`
**Description:** Retrieve a list of the latest amulet price votes (internal scan endpoint).

---

## Update History Queries

### `get_updates(after_migration_id=None, after_record_time=None, page_size=100, daml_value_encoding="compact_json")`
**Endpoint:** `POST /v2/updates`
**Parameters:**
- `after_migration_id` (Optional[int]): Start after this migration ID
- `after_record_time` (Optional[str]): Start after this record time (ISO format)
- `page_size` (int): Maximum number of updates to return (default: 100)
- `daml_value_encoding` (str): Encoding format for DAML values (default: "compact_json")

**Description:** Get update history in ascending order, paged. Uses /v2/updates which removes the offset field and sorts events lexicographically by ID.

### `get_update_by_id(update_id, daml_value_encoding="compact_json")`
**Endpoint:** `GET /v2/updates/{update_id}`
**Parameters:**
- `update_id` (str): The update ID to retrieve
- `daml_value_encoding` (str): Encoding format for DAML values (default: "compact_json")

**Description:** Get a specific update by ID.

---

## State/ACS Queries

### `get_acs_snapshot_timestamp(before, migration_id)`
**Endpoint:** `GET /v0/state/acs/snapshot-timestamp`
**Parameters:**
- `before` (str): ISO format datetime string
- `migration_id` (int): Migration ID

**Description:** Get the timestamp of the most recent snapshot before the given date.

### `get_acs(migration_id, record_time, record_time_match="exact", after=None, page_size=100, party_ids=None, templates=None)`
**Endpoint:** `POST /v0/state/acs`
**Parameters:**
- `migration_id` (int): Migration ID
- `record_time` (str): Record time (ISO format)
- `record_time_match` (str): Match type for record time (default: "exact")
- `after` (Optional[int]): Pagination token from previous response
- `page_size` (int): Maximum number of contracts to return (default: 100)
- `party_ids` (Optional[List[str]]): Filter by party IDs
- `templates` (Optional[List[str]]): Filter by template IDs

**Description:** Get the ACS (Active Contract Set) for a given migration id and record time.

### `force_acs_snapshot()`
**Endpoint:** `POST /v0/state/acs/force`
**Description:** Take a snapshot of the ACS at the current time. Note: This endpoint is disabled in production environments.

---

## Holdings Queries

### `get_holdings_state(migration_id, record_time, record_time_match="exact", after=None, page_size=100, owner_party_ids=None)`
**Endpoint:** `POST /v0/holdings/state`
**Parameters:**
- `migration_id` (int): Migration ID
- `record_time` (str): Record time (ISO format)
- `record_time_match` (str): Match type for record time (default: "exact")
- `after` (Optional[int]): Pagination token from previous response
- `page_size` (int): Maximum number of contracts to return (default: 100)
- `owner_party_ids` (Optional[List[str]]): Filter by owner party IDs

**Description:** Get active amulet contracts for a given migration id and record time.

### `get_holdings_summary(migration_id, record_time, record_time_match="exact", owner_party_ids=None, as_of_round=None)`
**Endpoint:** `POST /v0/holdings/summary`
**Parameters:**
- `migration_id` (int): Migration ID
- `record_time` (str): Record time (ISO format)
- `record_time_match` (str): Match type for record time (default: "exact")
- `owner_party_ids` (Optional[List[str]]): Filter by owner party IDs
- `as_of_round` (Optional[int]): Compute as of specific round

**Description:** Get aggregated amulet holdings summary. This is an aggregate of /v0/holdings/state by owner party ID with better performance than client-side computation.

---

## ANS (Amulet Name Service) Queries

### `get_ans_entries(page_size=100, name_prefix=None)`
**Endpoint:** `GET /v0/ans-entries`
**Parameters:**
- `page_size` (int): Maximum number of results returned (default: 100)
- `name_prefix` (Optional[str]): Filter entries by name prefix

**Description:** List all non-expired ANS entries.

### `get_ans_entry_by_party(party)`
**Endpoint:** `GET /v0/ans-entries/by-party/{party}`
**Parameters:**
- `party` (str): The user party ID that holds the ANS entry

**Description:** Get the first ANS entry for a user party.

### `get_ans_entry_by_name(name)`
**Endpoint:** `GET /v0/ans-entries/by-name/{name}`
**Parameters:**
- `name` (str): The ANS entry name

**Description:** Get ANS entry by exact name match.

---

## Mining Rounds Queries

### `get_closed_rounds()`
**Endpoint:** `GET /v0/closed-rounds`
**Description:** Get every closed mining round on the ledger still in post-close process.

### `get_open_and_issuing_mining_rounds(cached_open_mining_round_contract_ids=None, cached_issuing_round_contract_ids=None)`
**Endpoint:** `POST /v0/open-and-issuing-mining-rounds`
**Parameters:**
- `cached_open_mining_round_contract_ids` (Optional[List[str]]): Cached contract IDs for efficiency
- `cached_issuing_round_contract_ids` (Optional[List[str]]): Cached contract IDs for efficiency

**Description:** Get all current open and issuing mining rounds.

---

## Transfer Queries

### `get_transfer_preapproval_by_party(party)`
**Endpoint:** `GET /v0/transfer-preapprovals/by-party/{party}`
**Parameters:**
- `party` (str): Party ID

**Description:** Lookup a TransferPreapproval by the receiver party.

### `get_transfer_command_counter(party)`
**Endpoint:** `GET /v0/transfer-command-counter/{party}`
**Parameters:**
- `party` (str): Party ID

**Description:** Lookup a TransferCommandCounter by the receiver party.

### `get_transfer_command_status(sender, nonce)`
**Endpoint:** `GET /v0/transfer-command/status`
**Parameters:**
- `sender` (str): Sender party ID
- `nonce` (int): Nonce value

**Description:** Retrieve the status of all transfer commands of the given sender for the specified nonce.

---

## Event Queries

### `get_events(after_migration_id=None, after_record_time=None, page_size=100, daml_value_encoding="compact_json")`
**Endpoint:** `POST /v0/events`
**Parameters:**
- `after_migration_id` (Optional[int]): Start after this migration ID
- `after_record_time` (Optional[str]): Start after this record time (ISO format)
- `page_size` (int): Maximum number of events to return (default: 100)
- `daml_value_encoding` (str): Encoding format for DAML values (default: "compact_json")

**Description:** Get event history in ascending order, paged.

### `get_event_by_id(update_id, daml_value_encoding="compact_json")`
**Endpoint:** `GET /v0/events/{update_id}`
**Parameters:**
- `update_id` (str): The update ID to retrieve
- `daml_value_encoding` (str): Encoding format for DAML values (default: "compact_json")

**Description:** Get a specific event by update ID.

---

## Domain/Synchronizer Queries

### `get_participant_id_for_party(domain_id, party_id)`
**Endpoint:** `GET /v0/domains/{domain_id}/parties/{party_id}/participant-id`
**Parameters:**
- `domain_id` (str): The synchronizer ID to look up a mapping for
- `party_id` (str): The party ID to lookup a participant ID for

**Description:** Get the ID of the participant hosting a given party.

### `get_member_traffic_status(domain_id, member_id)`
**Endpoint:** `GET /v0/domains/{domain_id}/members/{member_id}/traffic-status`
**Parameters:**
- `domain_id` (str): The synchronizer ID to look up traffic for
- `member_id` (str): The participant or mediator whose traffic to look up (format: code::id::fingerprint)

**Description:** Get a member's traffic status as reported by the sequencer.

### `get_synchronizer_identities(domain_id_prefix)`
**Endpoint:** `GET /v0/synchronizer-identities/{domain_id_prefix}`
**Parameters:**
- `domain_id_prefix` (str): The domain ID prefix to query

**Description:** Get synchronizer identities for a domain.

### `get_synchronizer_bootstrapping_transactions(domain_id_prefix)`
**Endpoint:** `GET /v0/synchronizer-bootstrapping-transactions/{domain_id_prefix}`
**Parameters:**
- `domain_id_prefix` (str): The domain ID prefix to query

**Description:** Get synchronizer bootstrapping transactions.

---

## Migration Queries

### `get_migration_schedule()`
**Endpoint:** `GET /v0/migrations/schedule`
**Description:** Get scheduled synchronizer upgrade information if one is scheduled.

---

## Backfilling Queries

### `get_backfilling_migration_info(migration_id)`
**Endpoint:** `POST /v0/backfilling/migration-info`
**Parameters:**
- `migration_id` (int): Migration ID to query

**Description:** List all previous synchronizer migrations.

### `get_backfilling_updates_before(migration_id, synchronizer_id=None, before_timestamp=None, count=None)`
**Endpoint:** `POST /v0/backfilling/updates-before`
**Parameters:**
- `migration_id` (int): Migration ID
- `synchronizer_id` (Optional[str]): Optional synchronizer ID filter
- `before_timestamp` (Optional[str]): Optional timestamp filter (ISO format)
- `count` (Optional[int]): Optional maximum number of results

**Description:** Retrieve transactions and synchronizer reassignments prior to specification.

### `get_backfilling_status()`
**Endpoint:** `GET /v0/backfilling/status`
**Description:** Retrieve the status of the backfilling process.

### `import_backfilling_updates(updates)`
**Endpoint:** `POST /v0/backfilling/import-updates`
**Parameters:**
- `updates` (List[Dict[str, Any]]): List of update objects to import

**Description:** Import updates for backfilling (internal endpoint).

---

## Featured Apps Queries

### `get_featured_apps()`
**Endpoint:** `GET /v0/featured-apps`
**Description:** List every FeaturedAppRight registered with the DSO on the ledger.

### `get_featured_app_by_provider(provider_party_id)`
**Endpoint:** `GET /v0/featured-apps/{provider_party_id}`
**Parameters:**
- `provider_party_id` (str): Provider party ID

**Description:** Get FeaturedAppRight for a specific provider if it exists.

---

## Amulet Rules Queries

### `get_amulet_rules(cached_amulet_rules_contract_id=None, cached_amulet_rules_domain_id=None)`
**Endpoint:** `POST /v0/amulet-rules`
**Parameters:**
- `cached_amulet_rules_contract_id` (Optional[str]): Cached contract ID for efficiency
- `cached_amulet_rules_domain_id` (Optional[str]): Cached domain ID for efficiency

**Description:** Get amulet rules contract.

### `get_ans_rules(cached_ans_rules_contract_id=None, cached_ans_rules_domain_id=None)`
**Endpoint:** `POST /v0/ans-rules`
**Parameters:**
- `cached_ans_rules_contract_id` (Optional[str]): Cached contract ID for efficiency
- `cached_ans_rules_domain_id` (Optional[str]): Cached domain ID for efficiency

**Description:** Get ANS rules contract.

### `get_external_party_amulet_rules(cached_external_party_amulet_rules_contract_id=None, cached_external_party_amulet_rules_domain_id=None)`
**Endpoint:** `POST /v0/external-party-amulet-rules`
**Parameters:**
- `cached_external_party_amulet_rules_contract_id` (Optional[str]): Cached contract ID for efficiency
- `cached_external_party_amulet_rules_domain_id` (Optional[str]): Cached domain ID for efficiency

**Description:** Get external party amulet rules contract.

---

## Vote Queries

### `get_vote_requests_by_ids(vote_request_contract_ids)`
**Endpoint:** `POST /v0/voterequest`
**Parameters:**
- `vote_request_contract_ids` (List[str]): List of vote request contract IDs

**Description:** Look up several VoteRequests at once by their contract IDs.

### `get_vote_request_by_id(vote_request_contract_id)`
**Endpoint:** `GET /v0/voterequests/{vote_request_contract_id}`
**Parameters:**
- `vote_request_contract_id` (str): Vote request contract ID

**Description:** Look up a VoteRequest by contract ID.

### `get_all_vote_requests()`
**Endpoint:** `GET /v0/admin/sv/voterequests`
**Description:** List all active VoteRequests.

### `get_vote_results(filter_params=None)`
**Endpoint:** `POST /v0/admin/sv/voteresults`
**Parameters:**
- `filter_params` (Optional[Dict[str, Any]]): Optional filter parameters for vote results query

**Description:** Query vote results with optional filter parameters.

---

## Network Information

### `get_splice_instance_names()`
**Endpoint:** `GET /v0/splice-instance-names`
**Description:** Retrieve the UI names of various elements of this Splice network (network_name, network_favicon_url, amulet_name, amulet_name_acronym, name_service_name, name_service_name_acronym).

### `get_feature_support()`
**Endpoint:** `GET /v0/feature-support`
**Description:** Get feature support information (e.g., no_holding_fees_on_transfers).

---

## Health/Status Endpoints

### `health_check()`
**Endpoint:** `GET /readyz` (with fallback to `GET /v0/dso`)
**Description:** Check if the API is accessible. Returns True if API is healthy, False otherwise.

### `get_readiness()`
**Endpoint:** `GET /readyz`
**Description:** Check if the service is ready to accept requests.

### `get_liveness()`
**Endpoint:** `GET /livez`
**Description:** Check if the service is alive.

### `get_status()`
**Endpoint:** `GET /status`
**Description:** Get detailed service status including id, uptime, ports, extra, and active fields.

### `get_version()`
**Endpoint:** `GET /version`
**Description:** Get the service version and commit timestamp.

---

## Deprecated Endpoints (MainNet)

The following endpoints are marked as **deprecated** in the MainNet Scan Open API Reference. They remain functional but may be removed in future releases. The client implements `get_round_party_totals()` which uses one of these deprecated endpoints.

| Deprecated Endpoint | Replacement |
|---------------------|-------------|
| `POST /v0/round-party-totals` | No direct replacement yet (still functional) |
| `POST /v0/round-totals` | No direct replacement yet (still functional) |
| `POST /v0/activities` | Use `/v2/updates` for raw transaction data |
| `GET /v0/total-amulet-balance` | Use `/registry/metadata/v1/instruments/Amulet` token standard metadata API |
| `GET /v0/wallet-balance` | Use `/v0/holdings/summary` with `/v0/state/acs/snapshot-timestamp` |
| `GET /v0/amulet-config-for-round` | Use `/v0/amulet-rules` for current configuration |
| `GET /v0/top-providers-by-app-rewards` | No direct replacement yet |
| `GET /v0/top-validators-by-validator-rewards` | No direct replacement yet |
| `GET /v0/top-validators-by-purchased-traffic` | No direct replacement yet |
| `GET /v0/aggregated-rounds` | No direct replacement yet |
| `GET /v0/round-of-latest-data` | No direct replacement yet |
| `GET /v0/rewards-collected` | No direct replacement yet |
| `POST /v0/transactions` | Use `/v2/updates` (deprecated with known bugs) |
| `POST /v0/updates` | Use `/v2/updates` |
| `GET /v0/updates/{update_id}` | Use `/v2/updates/{update_id}` |
| `POST /v1/updates` | Use `/v2/updates` |
| `GET /v1/updates/{update_id}` | Use `/v2/updates/{update_id}` |

---

## Summary

**Total Endpoints Implemented:** 50 production endpoints

**API Version Support:**
- v0 endpoints: 42 endpoints (some marked deprecated in MainNet)
- v1 endpoints: 0 (deprecated, not implemented)
- v2 endpoints: 2 endpoints (updates)
- Common endpoints: 4 (readyz, livez, status, version)

**Coverage:**
- Core operations: ✅
- Administrative operations: ✅
- Backfilling operations: ✅
- Internal operations: ✅
- Health/Status operations: ✅
- Deprecated endpoints: Documented with migration guidance

This implementation provides coverage of all non-deprecated endpoints from the official MainNet Scan Open API specification, plus the `get_round_party_totals()` deprecated endpoint which is still functional and used by the rewards analysis system.
