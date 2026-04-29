# ADK Java Coding Agent

This project implements a small ADK-style Java coding agent. It asks an LLM to
generate Java production code, asks another LLM step to generate JUnit 5 tests,
runs real Java/JUnit tools, asks an improvement LLM step to fix failures, and
stores explanations in a local SQLite database.

The Java code and JUnit tests are not hard coded. They are produced from the task
prompt by the LLM backend you configure.

The agent structure is:

```text
SequentialAgent(
  LlmAgent(first version),
  LoopAgent(max_cycles=20, [
    LlmAgent(JUnit5 unit-test development),
    LlmAgent(run unit tests with tools),
    LlmAgent(improve code using failures),
    CheckResultAndEscalate
  ])
)
```

The explanation database records modularization decisions, data structure
choices, code-change reasons, files changed, new-line counts, compiler errors,
test results, and unified diffs for file changes.

## Requirements

These commands assume you are already in WSL Linux and already inside this
project directory.

Check Java and Python:

```bash
python3 --version
java -version
javac -version
```

The JUnit 5 Console Standalone jar is included here:

```text
tools/junit-platform-console-standalone-1.10.2.jar
```

You also need an LLM backend. The default is local Ollama.

Check Ollama:

```bash
curl http://127.0.0.1:11434/api/tags
```

If needed, pull a model:

```bash
ollama pull llama3.1
```

Then run the model:
```bash
ollama run llama3.1
```

## Run the Agent with Ollama

```bash
python3 -m adk_java_agent.cli \
  --llm-provider ollama \
  --model llama3.1 \
  --llm-timeout 900 \
  --project-root runs/my-demo \
  --junit-jar tools/junit-platform-console-standalone-1.10.2.jar \
  --task "Create a Calculator class with add, subtract, multiply, and divide"
```
> May need to wait around 10-15 minutes...

Expected output:

```text
All tests passed.
success=True
project_root=.../runs/my-demo
explanations_db=.../runs/my-demo/explanations.sqlite
```

Generated Java files are written under:

```text
runs/my-demo/src/main/java/
runs/my-demo/src/test/java/
```

## Run with an OpenAI-Compatible API

Set an API key:

```bash
export OPENAI_API_KEY="your-key-here"
```

Then run:

```bash
python3 -m adk_java_agent.cli \
  --llm-provider openai-compatible \
  --model gpt-4.1-mini \
  --api-base https://api.openai.com/v1 \
  --project-root runs/my-demo \
  --junit-jar tools/junit-platform-console-standalone-1.10.2.jar \
  --task "Create a Calculator class with add, subtract, multiply, and divide"
```

For a different OpenAI-compatible service, change `--api-base`, `--model`, and
optionally `--api-key-env`.

## Browse Explanations

Start the web viewer:

```bash
python3 -m adk_java_agent.web \
  --db runs/my-demo/explanations.sqlite \
  --port 8765
```

Open this URL in your browser:

```text
http://127.0.0.1:8765
```

Leave the terminal open while browsing. Press `Ctrl+C` to stop the web viewer.

Entries that created or changed files include an expanded `Diff` section.

## Optional: Simulated Tool Mode

This still uses the LLM for code and tests, but it does not run `javac` or JUnit.
It only checks that production and test Java files were generated.

```bash
python3 -m adk_java_agent.cli \
  --llm-provider ollama \
  --model llama3.1 \
  --simulate-tools \
  --project-root runs/local-demo \
  --task "Create a small Java Stack class with push, pop, peek, and isEmpty"
```

## Clean Generated Output

The agent writes generated projects under `runs/`.

```bash
rm -rf runs
```

Do not delete `adk_java_agent/` or `tools/`; those are required to run the
program.


## Contex Demo
![#1 first-version modularization](images/image-3.png)
![#2 first-version data_structure_selection](images/image-4.png)
![#3 junit5-tests-devel test_design](images/image-5.png)
![#4 and #5](images/image-6.png)
![#6 and #7](images/image-7.png)
![#8 and #9](images/image-8.png)