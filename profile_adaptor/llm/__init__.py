from profile_adaptor.config import Settings
from profile_adaptor.llm.ollama_client import OllamaClient
from profile_adaptor.llm.web_client import WebLLMClient


def create_llm_client(settings: Settings):
    timeout = float(getattr(settings, "llm_timeout", 60.0) or 60.0)
    if settings.provider == "web":
        return WebLLMClient(
            base_url=settings.web_llm_base_url,
            api_key=settings.web_llm_api_key,
            model=settings.web_llm_model,
            timeout=timeout,
        )
    return OllamaClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout=timeout,
    )
