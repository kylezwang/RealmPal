import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from api.models.player import PetInfo
from api.services.scraper import PET_NOT_FOUND_MSG, ScraperError, scrape_player_pet


@pytest.mark.asyncio
async def test_scrape_player_pet_times_out_with_friendly_message():
    async def slow_run():
        raise TimeoutError("playwright hung")

    with patch("api.services.scraper.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        with pytest.raises(ScraperError, match=PET_NOT_FOUND_MSG):
            await scrape_player_pet("TestUser")


@pytest.mark.asyncio
async def test_scrape_player_pet_raises_when_no_pet_on_page():
    with patch("api.services.scraper._playwright_browser") as browser_ctx:
        browser = AsyncMock()
        browser_ctx.return_value.__aenter__ = AsyncMock(return_value=browser)
        browser_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        page = AsyncMock()
        page.title = AsyncMock(return_value="Player - RealmEye")
        with patch("api.services.scraper._new_page", return_value=page):
            with patch("api.services.scraper._goto_with_retry", new_callable=AsyncMock):
                with patch(
                    "api.services.scraper._read_top_pet_from_page",
                    new_callable=AsyncMock,
                    return_value=None,
                ):
                    with pytest.raises(ScraperError, match=PET_NOT_FOUND_MSG):
                        await scrape_player_pet("PrivatePetOff")


@pytest.mark.asyncio
async def test_scrape_player_pet_returns_minimal_profile():
    top_pet = PetInfo(
        name="Reaper",
        sprite_sheet_url="https://example.com/pets.png",
        sprite_x=336,
        sprite_y=288,
        sprite_size=48,
    )
    with patch("api.services.scraper._playwright_browser") as browser_ctx:
        browser = AsyncMock()
        browser_ctx.return_value.__aenter__ = AsyncMock(return_value=browser)
        browser_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        page = AsyncMock()
        page.title = AsyncMock(return_value="Player - RealmEye")
        with patch("api.services.scraper._new_page", return_value=page):
            with patch("api.services.scraper._goto_with_retry", new_callable=AsyncMock):
                with patch(
                    "api.services.scraper._read_top_pet_from_page",
                    new_callable=AsyncMock,
                    return_value=top_pet,
                ):
                    profile = await scrape_player_pet("Turbine")
    assert profile.username == "Turbine"
    assert profile.top_pet == top_pet
    assert profile.characters == []
    assert profile.fame is None


@pytest.mark.asyncio
async def test_scrape_player_pet_opens_pets_of_instead_of_clicking_the_tab():
    urls: list[str] = []

    async def capture_goto(page, url, **kwargs):
        urls.append(url)

    top_pet = PetInfo(
        name="Reaper",
        sprite_sheet_url="https://example.com/pets.png",
        sprite_x=336,
        sprite_y=288,
        sprite_size=48,
    )
    with patch("api.services.scraper._playwright_browser") as browser_ctx:
        browser = AsyncMock()
        browser_ctx.return_value.__aenter__ = AsyncMock(return_value=browser)
        browser_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        page = AsyncMock()
        page.title = AsyncMock(return_value="Pets of Turbine - RealmEye")
        with patch("api.services.scraper._new_page", return_value=page):
            with patch(
                "api.services.scraper._goto_with_retry",
                new_callable=AsyncMock,
                side_effect=capture_goto,
            ):
                with patch(
                    "api.services.scraper._read_top_pet_from_page",
                    new_callable=AsyncMock,
                    return_value=top_pet,
                ):
                    await scrape_player_pet("Turbine")
    assert urls
    assert urls[0].endswith("/pets-of/Turbine")
