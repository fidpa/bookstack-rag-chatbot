"""The compose file and .env.example stay in step."""

import re

import yaml

from conftest import ROOT

COMPOSE = (ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")


def test_the_chatbot_port_is_published_on_loopback_by_default():
    # The allow-list and the rate limit trust the connecting address, so a port
    # open to the network defeats TRUSTED_PROXY_HOPS.
    ports = yaml.safe_load(COMPOSE)["services"]["chatbot"]["ports"]
    assert ports == ["${CHATBOT_BIND:-127.0.0.1}:${CHATBOT_PORT:-8888}:8888"]


def test_every_variable_the_compose_file_reads_is_in_env_example():
    used = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", COMPOSE))
    documented = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE, re.M))
    assert used - documented == set()


def test_the_chatbot_runs_as_the_user_that_owns_its_data():
    assert yaml.safe_load(COMPOSE)["services"]["chatbot"]["user"] == "1000:1000"
