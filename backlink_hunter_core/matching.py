"""Target matching logic across the four supported match modes."""

from __future__ import annotations

from dataclasses import dataclass

from .models import MatchMode

from .normalize import (

    extract_hostname,

    normalize_target_domain,

    normalize_target_hostname,

    normalize_url,

    path_of,

    registrable_domain,

)

@dataclass

class TargetSpec:

    raw: str

    mode: str

    domain: str = ""

    hostname: str = ""

    url: str = ""

    path_prefix: str = ""

    @classmethod

    def parse(cls, raw: str, mode: str) -> "TargetSpec":

        raw = (raw or "").strip()

        spec = cls(raw=raw, mode=mode)

        spec.domain = normalize_target_domain(raw)

        spec.hostname = normalize_target_hostname(raw)

        if "//" in raw or "/" in raw.split("?")[0].strip("/"):

            spec.url = normalize_url(raw if "//" in raw else "https://" + raw)

            spec.path_prefix = path_of(spec.url)

        else:

            spec.url = normalize_url("https://" + raw)

            spec.path_prefix = "/"

        return spec

def link_matches_target(resolved_url: str, spec: TargetSpec) -> bool:

    host = extract_hostname(resolved_url)

    if not host:

        return False

    if spec.mode == MatchMode.EXACT_HOSTNAME:

        return host == spec.hostname

    if spec.mode == MatchMode.ROOT_DOMAIN:

        return registrable_domain(host) == spec.domain

    if spec.mode == MatchMode.EXACT_URL:

        return normalize_url(resolved_url) == spec.url

    if spec.mode == MatchMode.PATH_PREFIX:

        if registrable_domain(host) != spec.domain:

            return False

        return path_of(normalize_url(resolved_url)).startswith(spec.path_prefix)

    return registrable_domain(host) == spec.domain
