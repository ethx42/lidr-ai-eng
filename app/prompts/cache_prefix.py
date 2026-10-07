"""Where a rendered system prompt stops being the same for every request. No imports, so a
provider can split a system prompt without loading the prompt stack."""

# Every version's system prompt is identical up to here (the provider-side cache prefix); the enum
# blocks and v3's session metadata follow.
STATIC_END = "</reference_estimations>\n"


def split_system(system: str) -> tuple[str, str]:
    """(static prefix, tail). A system prompt without the boundary is all prefix."""
    end = system.find(STATIC_END)
    cut = len(system) if end < 0 else end + len(STATIC_END)
    return system[:cut], system[cut:]
