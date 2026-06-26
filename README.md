# Backport Agent Leaderboard

A benchmarking platform that evaluates automated backporting tools against a curated dataset of known-good backports from open-source projects. Tools are ranked by accuracy, cost, speed, and token efficiency on a hosted leaderboard.

## How It Works

1. **Dataset** — A CSV of known-good backports (repo, original commit SHA, backport commit SHA) serves as ground truth.
2. **Run** — The orchestrator checks out each repo, sets up branches, invokes the tool under test, and compares the generated diff against the known-good backport using semantic equivalence (not byte-identical matching).
3. **Leaderboard** — Results are aggregated into a ranked comparison, deployable as a Gradio app on Hugging Face Spaces.

## Quick Start

```bash
# Run benchmarks with a specific tool
./run --tool amalgamator-opus

# Run against a single repo or limit entries
./run --tool amalgamator-opus --repo line/armeria --limit 10

# Run a specific backport entry by commit SHAs
./run --tool amalgamator-opus --original <orig_sha> --backport <backport_sha>

# View results for a tool
./results --tool amalgamator-opus

# Display the leaderboard
./leaderboard

# Add a new backport entry to the dataset
./add-backport --repo owner/repo --original <sha> --backport <sha>
```

## Configuration

The system is driven by a single YAML config file that defines global settings and tool definitions.

```yaml
semantic_diff:
  model: "claude-opus-4-6"
  command: |
    claude -m ${SEMANTIC_DIFF_MODEL} -p "Compare @${ORIGINAL_DIFF_PATH} and @${PIPELINE_DIFF_PATH}...
    Respond with JSON: {\"equivalent\": true} or {\"equivalent\": false, \"reason\": \"...\"}"

default_tool: "amalgamator-opus"
timeout: 1800

tools:
  amalgamator-opus:
    display_name: "Amalgamator / Opus 4.6"
    model: "claude-opus-4-6"
    config:
      tool_location: "/path/to/amalgamator"
    commands:
      setup: |
        # prepare config files, credentials, working state
      generate_diff: |
        # produce a diff and write it to ${PIPELINE_DIFF_PATH}
      get_stats: |
        # emit JSON metrics to stdout
```

## Adding a Tool

Every tool must satisfy a simple command contract — three shell commands the orchestrator calls during a run:

| Command | Required | Description |
|---|---|---|
| `setup` | No | Prepare config, credentials, or working state before generating a diff. |
| `generate_diff` | Yes | Run the backporting logic. Must write the resulting diff to `${PIPELINE_DIFF_PATH}`. |
| `get_stats` | No | Print a JSON object to stdout with run metrics. |

### Environment Variables

The orchestrator provides these variables to every command:

| Variable | Description |
|---|---|
| `${REPO}` | Repository identifier (e.g., `line/armeria`) |
| `${ORIG_SHA}` | SHA of the original fix commit |
| `${BACKPORT_SHA}` | SHA of the known-good backport commit |
| `${RUN_KEY}` | Unique key for this run (`{orig_sha}-{backport_sha}`) |
| `${PROJECT_PATH}` | Absolute path to the local project clone |
| `${SOURCE_BRANCH}` | Branch containing the original commit |
| `${TARGET_WORKSPACE}` | Path to the isolated worktree for the target branch |
| `${ORIGINAL_DIFF_PATH}` | Path where the orchestrator writes the known-good backport diff (extracted from `${BACKPORT_SHA}`) |
| `${PIPELINE_DIFF_PATH}` | Path where `generate_diff` must write its output |

Tool-specific `config` values are exposed as `${CONFIG_<KEY>}` (uppercased).

### Stats Output Schema

The `get_stats` command should print JSON to stdout:

```json
{
  "time": 180.5,
  "llm_calls": 3,
  "cost": 0.74,
  "input_tokens": 200000,
  "output_tokens": 4800
}
```

All fields are optional. Unknown fields are ignored.

## Leaderboard

The leaderboard is a hosted web app with two main views:

**Leaderboard tab** — One row per tool. Shows pass rate averaged across benchmark subsets, with per-benchmark columns.

**Benchmark Runs tab** — One row per individual run. Shows score, average cost, time, and token usage per task. Additional columns available via a column picker.

Both views support search, sorting, filtering by category (open-source / proprietary), and filtering by repository or language.

### Result Data Format

Each benchmark run is stored as a self-contained JSON file:

```json
{
  "benchmark": {
    "name": "backportbench-java",
    "repo": "owner/backportbench",
    "num_tasks": 250,
    "url": "https://..."
  },
  "tool": {
    "display_name": "Amalgamator / Opus 4.6",
    "is_oss": true,
    "url": "https://..."
  },
  "metrics": {
    "score": 0.72,
    "n_tasks": 250,
    "n_errors": 3,
    "cost_usd": 185.50,
    "mean_cost_usd_per_task": 0.74,
    "mean_time_seconds_per_task": 180,
    "mean_input_tokens_per_task": 200000,
    "mean_output_tokens_per_task": 4800
  }
}
```

The leaderboard reads all JSON files from a results directory and can be fully regenerated at any time.

## Dataset

The benchmark dataset contains 1,032 verified backports from open-source projects. Each entry is classified by complexity based on how much the backport diff diverges from the original fix:

| Complexity | Count | % | Description |
|---|---|---|---|
| **Easy** | 758 | 73.4% | Original fix and backport are essentially identical — same files, same changes |
| **Medium** | 170 | 16.5% | Some adaptations needed — minor context differences, adjusted imports, or small code changes |
| **Complex** | 104 | 10.1% | Significant divergence — different files changed, substantial rewrites due to API or feature differences between versions |

```
Easy    ████████████████████████████████████████████████████████░░░░░░░░░░░░░░░  73.4%
Medium  ████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  16.5%
Complex ███████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  10.1%
```

### Counts by Repo and Classification

| Repo | Complex | Easy | Medium | Total |
|---|---|---|---|---|
| Graylog2/graylog2-server | 2 | 19 | 0 | 21 |
| ag-grid/ag-grid | 0 | 1 | 0 | 1 |
| angular/angular | 0 | 1 | 0 | 1 |
| apache/activemq | 0 | 3 | 0 | 3 |
| apache/airflow | 0 | 5 | 0 | 5 |
| apache/camel | 0 | 34 | 5 | 39 |
| apache/cxf | 0 | 17 | 1 | 18 |
| apache/cxf-fediz | 0 | 0 | 1 | 1 |
| apache/druid | 1 | 6 | 0 | 7 |
| apache/hadoop | 0 | 7 | 3 | 10 |
| apache/hbase | 0 | 20 | 1 | 21 |
| apache/james-project | 0 | 1 | 0 | 1 |
| apache/kafka | 0 | 2 | 1 | 3 |
| apache/lucene-solr | 0 | 5 | 2 | 7 |
| apache/mina-sshd | 0 | 1 | 0 | 1 |
| apache/myfaces | 0 | 1 | 0 | 1 |
| apache/pulsar | 0 | 1 | 0 | 1 |
| apache/rocketmq | 1 | 0 | 0 | 1 |
| apache/struts | 3 | 5 | 2 | 10 |
| apache/superset | 0 | 0 | 2 | 2 |
| apache/syncope | 1 | 0 | 0 | 1 |
| apache/tomcat | 1 | 48 | 6 | 55 |
| apache/zookeeper | 0 | 2 | 0 | 2 |
| apollographql/apollo-server | 2 | 0 | 0 | 2 |
| autovance/ftp-srv | 0 | 2 | 0 | 2 |
| axios/axios | 1 | 0 | 0 | 1 |
| caolan/async | 1 | 0 | 0 | 1 |
| ckan/ckan | 0 | 1 | 0 | 1 |
| cloudfoundry/uaa | 5 | 25 | 10 | 40 |
| crate/crate | 4 | 105 | 22 | 131 |
| cri-o/cri-o | 3 | 3 | 3 | 9 |
| django/django | 23 | 60 | 53 | 136 |
| dropwizard/dropwizard | 0 | 0 | 1 | 1 |
| eclipse-vertx/vert.x | 0 | 2 | 0 | 2 |
| elastic/elasticsearch | 3 | 86 | 7 | 96 |
| elastic/logstash | 0 | 3 | 0 | 3 |
| enonic/xp | 0 | 2 | 0 | 2 |
| fastify/fastify-bearer-auth | 0 | 1 | 0 | 1 |
| fastify/fastify-websocket | 0 | 1 | 0 | 1 |
| feathersjs/feathers | 1 | 0 | 0 | 1 |
| florianholzapfel/express-restify-mongoose | 1 | 0 | 0 | 1 |
| geoserver/geoserver | 0 | 5 | 0 | 5 |
| grpc/grpc-java | 1 | 27 | 0 | 28 |
| hapijs/hoek | 1 | 0 | 0 | 1 |
| hibernate/hibernate-orm | 1 | 13 | 1 | 15 |
| hibernate/hibernate-validator | 0 | 1 | 0 | 1 |
| horazont/aioxmpp | 0 | 1 | 0 | 1 |
| indutny/node-ip | 0 | 1 | 0 | 1 |
| isaacs/node-tar | 0 | 7 | 2 | 9 |
| jenkinsci/jenkins | 1 | 5 | 0 | 6 |
| jenkinsci/parameterized-trigger-plugin | 0 | 1 | 0 | 1 |
| jenkinsci/ssh-agent-plugin | 0 | 1 | 0 | 1 |
| jenkinsci/support-core-plugin | 0 | 1 | 0 | 1 |
| jetty/jetty.project | 1 | 0 | 0 | 1 |
| jquery/jquery | 0 | 0 | 1 | 1 |
| json5/json5 | 0 | 0 | 1 | 1 |
| jupyter-server/jupyter_server | 0 | 1 | 0 | 1 |
| jupyterhub/jupyterhub | 0 | 1 | 0 | 1 |
| line/armeria | 0 | 1 | 0 | 1 |
| ljharb/qs | 0 | 8 | 0 | 8 |
| matrix-org/synapse | 0 | 1 | 0 | 1 |
| minimistjs/minimist | 1 | 0 | 0 | 1 |
| nautobot/nautobot | 3 | 2 | 2 | 7 |
| netty/netty | 0 | 1 | 0 | 1 |
| nodejs/undici | 1 | 1 | 1 | 3 |
| npm/node-tar | 1 | 0 | 0 | 1 |
| npm/npm | 0 | 1 | 0 | 1 |
| npm/ssri | 0 | 2 | 0 | 2 |
| openjdk/jdk11u-dev | 0 | 1 | 0 | 1 |
| openjdk/jdk21u-dev | 0 | 51 | 3 | 54 |
| opensearch-project/sql | 0 | 13 | 0 | 13 |
| openstack/aodh | 0 | 1 | 0 | 1 |
| openstack/cinder | 1 | 1 | 2 | 4 |
| openstack/glance | 0 | 5 | 4 | 9 |
| openstack/horizon | 0 | 5 | 0 | 5 |
| openstack/ironic | 1 | 1 | 0 | 2 |
| openstack/keystone | 1 | 13 | 3 | 17 |
| openstack/neutron | 0 | 5 | 1 | 6 |
| openstack/nova | 7 | 21 | 4 | 32 |
| openstack/octavia | 0 | 3 | 0 | 3 |
| openstack/os-vif | 1 | 0 | 0 | 1 |
| openstack/swift | 0 | 3 | 0 | 3 |
| panva/jose | 1 | 0 | 0 | 1 |
| pydantic/pydantic | 1 | 2 | 0 | 3 |
| python-poetry/poetry-core | 0 | 1 | 0 | 1 |
| qos-ch/logback | 0 | 0 | 1 | 1 |
| quarkusio/quarkus | 0 | 4 | 3 | 7 |
| redis/redis-py | 1 | 0 | 0 | 1 |
| rvagg/bl | 2 | 0 | 0 | 2 |
| saleor/saleor | 0 | 6 | 0 | 6 |
| sindresorhus/dot-prop | 1 | 0 | 0 | 1 |
| sindresorhus/file-type | 1 | 0 | 1 | 2 |
| socketio/engine.io | 2 | 0 | 0 | 2 |
| socketio/socket.io-client-java | 0 | 0 | 1 | 1 |
| socketio/socket.io-parser | 4 | 1 | 0 | 5 |
| spring-attic/spring-security-oauth | 0 | 3 | 0 | 3 |
| spring-projects/spring-data-commons | 0 | 1 | 0 | 1 |
| spring-projects/spring-data-rest | 0 | 1 | 0 | 1 |
| spring-projects/spring-framework | 6 | 22 | 6 | 34 |
| spring-projects/spring-kafka | 0 | 1 | 0 | 1 |
| spring-projects/spring-security | 0 | 4 | 0 | 4 |
| tensorflow/tensorflow | 3 | 3 | 5 | 11 |
| terser/terser | 0 | 0 | 1 | 1 |
| tinymce/tinymce | 2 | 0 | 1 | 3 |
| undertow-io/undertow | 0 | 3 | 0 | 3 |
| urllib3/urllib3 | 2 | 1 | 1 | 4 |
| vaadin/flow-components | 0 | 1 | 0 | 1 |
| vitejs/vite | 2 | 4 | 2 | 8 |
| wagtail/wagtail | 0 | 5 | 0 | 5 |
| websockets/ws | 0 | 1 | 3 | 4 |
| xmldom/xmldom | 0 | 2 | 0 | 2 |
| xwiki/xwiki-commons | 0 | 2 | 0 | 2 |
| xwiki/xwiki-platform | 1 | 15 | 0 | 16 |
| **TOTAL** | **104** | **758** | **170** | **1032** |

Classification is computed by fetching the patch for both the original and backport commits, normalizing them (stripping metadata, context lines, and line numbers), and comparing via sequence similarity and file overlap metrics.

## Design Principles

- **Tool-agnostic** — Any tool invocable from the shell can participate via the command contract.
- **Configuration-aware** — The same tool with different LLMs or settings appears as separate leaderboard entries, each identified by its `display_name`.
- **Reproducible** — Runs pin exact commit SHAs so results are comparable across machines.
- **Isolated** — Each run operates in its own worktree. Concurrent runs against the same repo don't interfere.
- **Resilient** — Individual run failures don't abort the batch. Runs can be resumed from where they left off.
- **Extensible** — Adding a new tool requires only defining its commands in the config file. No orchestrator or leaderboard changes needed.
