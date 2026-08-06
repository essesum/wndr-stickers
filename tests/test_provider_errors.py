import httpx
import pytest

from skill.wndr_stickers.src import imagegen


def test_provider_error_body_is_not_persistable_in_exception():
    secretish_body = "request payload with private context"
    response = httpx.Response(429, text=secretish_body)
    with pytest.raises(imagegen.ProviderUnavailable) as caught:
        imagegen._raise_for_soft_failure(response, "provider")
    assert "HTTP 429" in str(caught.value)
    assert secretish_body not in str(caught.value)
