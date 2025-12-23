.PHONY: infra-up infra-down pull-model dev install clean

OLLAMA_CONTAINER := codemapper-ollama
OLLAMA_PORT := 11434
MODEL := qwen2.5-coder:14b

infra-up:
	@docker run -d \
		--name $(OLLAMA_CONTAINER) \
		-p $(OLLAMA_PORT):11434 \
		-v ollama_data:/root/.ollama \
		--gpus all 2>/dev/null || \
	docker run -d \
		--name $(OLLAMA_CONTAINER) \
		-p $(OLLAMA_PORT):11434 \
		-v ollama_data:/root/.ollama \
		ollama/ollama:latest
	@echo "Ollama running on http://localhost:$(OLLAMA_PORT)"

infra-down:
	@docker stop $(OLLAMA_CONTAINER) 2>/dev/null || true
	@docker rm $(OLLAMA_CONTAINER) 2>/dev/null || true
	@echo "Ollama stopped"

pull-model:
	@docker exec $(OLLAMA_CONTAINER) ollama pull $(MODEL)
	@echo "Model $(MODEL) ready"

install:
	pip install -e .

dev:
	python -m codemapper.main

clean:
	rm -rf maps/ mapper.lock
