"""
Async Playwright scraper for Realmeye.com and UmiEnjoyers.com.

Design principles (learned from Certio):
- Always use `async with` for Playwright context | no manual cleanup
- Structured logging via loguru, never print()
- Return typed Pydantic models, not raw dicts
- Raise specific exceptions, never swallow silently

Reliability notes:
- Realmeye is picky about obviously-automated traffic. A bare
  `chromium.launch()` + default context uses Playwright's automation flags
  and a "HeadlessChrome" UA, which can get navigation requests killed
  mid-flight (Playwright surfaces this as `net::ERR_ABORTED`). Launching
  with a realistic UA/viewport/locale and the automation-flag disabled
  makes RealmEye's page consistently reachable.
- Transient navigation failures (aborted/timeout) are retried once before
  giving up, since they're often a one-off hiccup rather than a hard block.
"""
import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from loguru import logger
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout

from ..models.player import CharacterStats, CharacterSummary, EquipmentItem, ExaltationEntry, PetInfo, PlayerProfile
from ..models.item import ItemProfile

REALMEYE_BASE = "https://www.realmeye.com"
UMI_BASE = "https://www.umienjoyers.com"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# One Chromium at a time | parallel launches crash the driver.
_PW_SEM = asyncio.Semaphore(1)


@asynccontextmanager
async def _playwright_browser():
    async with _PW_SEM:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                yield browser
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass


class ScraperError(Exception):
    """Raised when scraping fails after retries."""


PET_NOT_FOUND_MSG = "Sorry, I wasn't able to find a pet. Please try again later."
PET_LOOKUP_TIMEOUT_SECONDS = 10.0


def _pick_top_pet(pets: list[dict]) -> Optional[dict]:
    """RealmEye top pet is the highest ability total, not the first yard slot."""
    scored: list[dict] = []
    for pet in pets or []:
        name = (pet.get("name") or "").strip()
        if not name:
            continue
        levels = [int(n) for n in (pet.get("levels") or []) if isinstance(n, (int, float))]
        scored.append({**pet, "name": name, "levels": levels})
    if not scored:
        return None

    def key(pet: dict) -> tuple[int, int, int]:
        levels = pet.get("levels") or []
        return (
            sum(levels),
            max(levels) if levels else 0,
            min(levels) if levels else 0,
        )

    return max(scored, key=key)


# Waits for RealmEye's own `drawCharacters()` (see characters.js) to finish.
# That function composites each character's real, dye-colored portrait onto
# a runtime <canvas> and injects a `<style>` overriding `.character`'s
# background-image with a `data:image/png;base64,...` URI + new
# `background-position !important`. Until that finishes, `a.character`'s
# background-position still points at the *static* base/outline sprite in
# sheets.png (no dye colors applied), which is why an early extraction
# looked like a flat gray silhouette instead of a real portrait.
_WAIT_FOR_CHARACTER_COMPOSITE_JS = """() => {
  const el = document.querySelector('a.character');
  return el && getComputedStyle(el).backgroundImage.startsWith('url("data:');
}"""

# Pulls one player's whole Characters table (portrait, class/fame/place,
# equipped items, maxed-stats readout) out of the DOM in a single round
# trip. Kept as raw CSS background-image/background-position/computed-size
# strings here; `_parse_character_row` below turns that into typed fields.
#
# Each equipped item also carries RealmEye's rarity-tiered decoration:
#   - a "slot" frame (e.g. Divine's 4 gold diamonds) painted via a
#     `::before` pseudo-element cropped from slots.png
#   - a colored glow via `filter: drop-shadow(<rgb> 0 0 3px)` on the icon
#     itself, colored the same as the slot frame
# Both are read via getComputedStyle(el, '::before'/none) rather than
# hardcoding a rarity->color/offset table, since RealmEye computes them
# straight off the `item-wrapper` class name (e1..e4, s2/s3, or none).
_CHARACTER_TABLE_JS = """
(table) => {
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  return rows.map(row => {
    const cells = row.querySelectorAll('td');
    const charEl = cells[1] ? cells[1].querySelector('a.character') : null;
    const charStyle = charEl ? getComputedStyle(charEl) : null;
    const equipWrappers = cells[6] ? Array.from(cells[6].querySelectorAll('span.item-wrapper')) : [];
    const equipment = equipWrappers.map(w => {
      const itemEl = w.querySelector('span.item');
      const istyle = itemEl ? getComputedStyle(itemEl) : null;
      const before = getComputedStyle(w, '::before');
      const hasSlot = before.backgroundImage && before.backgroundImage !== 'none' && before.width !== 'auto';
      const a = w.querySelector('a');
      return {
        tooltip: w.getAttribute('title') || '',
        wiki_href: a ? a.getAttribute('href') : null,
        bg_image: istyle ? istyle.backgroundImage : null,
        bg_position: itemEl ? itemEl.style.backgroundPosition : null,
        width: istyle ? istyle.width : null,
        slot_bg_image: hasSlot ? before.backgroundImage : null,
        slot_bg_position: hasSlot ? before.backgroundPosition : null,
        slot_width: hasSlot ? before.width : null,
        glow_filter: istyle ? istyle.filter : null,
      };
    });
    const statsEl = cells[7] ? cells[7].querySelector('span.player-stats') : null;
    const placeA = cells[5] ? cells[5].querySelector('a') : null;
    return {
      class_name: cells[2] ? cells[2].textContent.trim() : '',
      fame: cells[4] ? cells[4].textContent.trim() : '',
      place: cells[5] ? cells[5].textContent.trim() : '',
      // Class placement (e.g. "#366") links to that class's leaderboard,
      // e.g. /top-druids/501 | only present once a character is ranked.
      place_href: placeA ? placeA.getAttribute('href') : null,
      char_bg_image: charStyle ? charStyle.backgroundImage : null,
      // Must read the *computed* position, not the element's inline style
      // attribute | drawCharacters() overrides it via a `!important` rule
      // in an injected <style> tag (targeting #id), which beats the inline
      // style's specificity but doesn't change the attribute value itself.
      char_bg_position: charStyle ? charStyle.backgroundPosition : null,
      char_width: charStyle ? charStyle.width : null,
      char_height: charStyle ? charStyle.height : null,
      stats_text: statsEl ? statsEl.textContent.trim() : null,
      // RealmEye puts the real HP/MP/ATT/... values on the 8/8 badge so
      // hovering it can show a per-stat breakdown. Same 8-length arrays
      // the site's own tooltip uses (base + item bonuses).
      stats_data: statsEl ? statsEl.getAttribute('data-stats') : null,
      stats_bonuses: statsEl ? statsEl.getAttribute('data-bonuses') : null,
      equipment: equipment,
    };
  });
}
"""

# RealmEye's "Exaltations" tab (a separate lazy-loaded AJAX table, same
# `table.tablesorter` shell as the Characters tab) | one row per *class*
# (exaltation bonuses apply to every character of that class, not to one
# specific character), with the class's portrait, total exaltation count,
# and the 8 RotMG stats' bonus amounts. A fully-exalted stat gets a
# `class="maxed"` span (HP/MP max at +25, the other six stats at +5), which
# we don't currently read separately | the frontend derives "maxed" from
# the raw number instead of relying on this class name.
# Pet Yard table: each row is a pet sprite plus Heal / Magic Heal / Electric
# (or similar) levels. RealmEye does not sort this by strength, so we read
# every row and pick the highest ability total in Python.
_PET_YARD_JS = """() => {
  const pets = [];
  const seen = new Set();
  const pushPet = (el, levels) => {
    const name = (el.getAttribute("title") || "").trim();
    if (!name || seen.has(name + JSON.stringify(levels))) return;
    seen.add(name + JSON.stringify(levels));
    const style = el.getAttribute("style") || "";
    const pos = /background-position:\\s*(-?\\d+)px\\s+(-?\\d+)px/.exec(style);
    const sheet = getComputedStyle(el).backgroundImage;
    const size = getComputedStyle(el).width;
    pets.push({
      name,
      levels,
      sheet,
      size,
      x: pos ? Math.abs(Number(pos[1])) : null,
      y: pos ? Math.abs(Number(pos[2])) : null,
    });
  };
  const abilityNums = (text) => {
    const nums = [];
    for (const match of String(text || "").matchAll(/\\b(\\d{1,3})\\b/g)) {
      const n = Number(match[1]);
      if (n >= 1 && n <= 100) nums.push(n);
    }
    return nums.slice(0, 3);
  };
  for (const table of document.querySelectorAll("table")) {
    const headers = [...table.querySelectorAll("thead th, tr th")].map(
      (th) => (th.textContent || "").toLowerCase(),
    );
    if (!headers.some((h) => /ability|pet/.test(h))) continue;
    const abilityIdx = headers
      .map((h, i) => (/ability/.test(h) ? i : -1))
      .filter((i) => i >= 0);
    for (const row of table.querySelectorAll("tbody tr")) {
      const pet = row.querySelector("span.pet[title]");
      if (!pet) continue;
      const cells = [...row.querySelectorAll("td")];
      let levels = [];
      if (abilityIdx.length) {
        for (const i of abilityIdx) {
          levels.push(...abilityNums(cells[i] ? cells[i].innerText : ""));
        }
        levels = levels.slice(0, 3);
      } else {
        levels = abilityNums(
          cells.slice(1).map((td) => td.innerText).join(" "),
        );
      }
      pushPet(pet, levels);
    }
  }
  if (!pets.length) {
    for (const el of document.querySelectorAll("span.pet[title]")) {
      const host = el.closest("tr, li, div") || el.parentElement;
      pushPet(el, abilityNums(host ? host.innerText : ""));
    }
  }
  return pets;
}"""


_EXALTATION_TABLE_JS = """
(table) => {
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  return rows.map(row => {
    const cells = row.querySelectorAll('td');
    const charEl = cells[0] ? cells[0].querySelector('a.character') : null;
    const charStyle = charEl ? getComputedStyle(charEl) : null;
    const cellText = (i) => cells[i] ? cells[i].textContent.trim() : null;
    return {
      class_name: cellText(1) || '',
      exaltation_count: cellText(2),
      max_hp: cellText(3),
      max_mp: cellText(4),
      attack: cellText(5),
      defense: cellText(6),
      speed: cellText(7),
      dexterity: cellText(8),
      vitality: cellText(9),
      wisdom: cellText(10),
      char_bg_image: charStyle ? charStyle.backgroundImage : null,
      char_bg_position: charStyle ? charStyle.backgroundPosition : null,
      char_width: charStyle ? charStyle.width : null,
      char_height: charStyle ? charStyle.height : null,
    };
  });
}
"""


def _parse_css_url(bg_image: Optional[str]) -> Optional[str]:
    """Extract the URL out of a computed `background-image: url("...")` value."""
    if not bg_image:
        return None
    match = re.search(r'url\("?([^")]+)"?\)', bg_image)
    return match.group(1) if match else None


def _parse_css_px(value: Optional[str]) -> Optional[int]:
    """Parse a computed pixel value like '48px' or a `background-position`
    coordinate like '-336px' into a plain int (sign preserved)."""
    if not value:
        return None
    match = re.search(r"(-?\d+)px", value)
    return int(match.group(1)) if match else None


def _parse_background_position(value: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not value:
        return None, None
    # Browsers normalize an exact 0,0 offset to "0% 0%" instead of "0px 0px"
    # in computed styles (seen on the Uncommon/e1 slot frame, which sits at
    # the sheet's origin) | treat that as (0, 0) rather than "unparseable".
    if re.fullmatch(r"\s*0%\s+0%\s*", value):
        return 0, 0
    match = re.search(r"(-?\d+)px\s+(-?\d+)px", value)
    if not match:
        return None, None
    return abs(int(match.group(1))), abs(int(match.group(2)))


def _parse_glow_color(filter_value: Optional[str]) -> Optional[str]:
    """Extract the `rgb(...)` color out of a computed
    `filter: drop-shadow(rgb(r, g, b) 0px 0px 3px)` value. Plain/no-rarity
    items still get a gray drop-shadow from RealmEye, so callers that only
    care about *rarity* glow should treat a gray result as "no glow"."""
    if not filter_value:
        return None
    match = re.search(r"drop-shadow\((rgba?\([^)]+\))", filter_value)
    return match.group(1) if match else None


def _parse_signed_int(value: Optional[str]) -> Optional[int]:
    """Parse an exaltation stat cell like '+5' or a plain count like '16'."""
    if not value:
        return None
    match = re.search(r"-?\d+", value)
    return int(match.group(0)) if match else None


# RealmEye's `data-stats` array order (confirmed against an 8/8 Archer:
# ATT/DEF/SPD/VIT/WIS/DEX match class maxes). This is NOT in-game HUD
# order | HUD puts DEX before VIT.
_STAT_KEYS = (
    "hp",
    "mp",
    "attack",
    "defense",
    "speed",
    "vitality",
    "wisdom",
    "dexterity",
)


def _stats_from_eight(values: list) -> Optional[CharacterStats]:
    if not isinstance(values, list) or len(values) < 8:
        return None
    parsed: dict[str, Optional[int]] = {}
    for i, key in enumerate(_STAT_KEYS):
        try:
            parsed[key] = int(values[i])
        except (TypeError, ValueError):
            parsed[key] = None
    return CharacterStats(**parsed)


def _parse_stat_payload(
    raw: Optional[str],
) -> tuple[Optional[CharacterStats], Optional[CharacterStats]]:
    """Parse RealmEye `data-stats`.

    Current format is a nested JSON payload:
      [[hp,mp,att,def,spd,vit,wis,dex], [bonuses...], ...]
    Older pages used a flat 8-length array, sometimes with a separate
    `data-bonuses` attribute.
    """
    if not raw:
        return None, None
    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None, None
    if not isinstance(values, list) or not values:
        return None, None
    if isinstance(values[0], list):
        totals = _stats_from_eight(values[0])
        bonuses = (
            _stats_from_eight(values[1])
            if len(values) > 1 and isinstance(values[1], list)
            else None
        )
        return totals, bonuses
    return _stats_from_eight(values), None


def _equipment_name_from_tooltip(tooltip: str, wiki_href: Optional[str]) -> str:
    """
    Derive a clean display name for an item. The tooltip's first line is
    "<Rarity> <Name> <Tier>" (e.g. "Rare Thousand Shot UT"), which is awkward
    to split reliably, so prefer reconstructing the name from the wiki
    slug (e.g. "/wiki/thousand-shot" -> "Thousand Shot") and only fall back
    to the raw tooltip line if there's no link.
    """
    if wiki_href:
        slug = wiki_href.rstrip("/").split("/")[-1]
        return slug.replace("-", " ").title()
    return tooltip.split("\n")[0].strip() if tooltip else "Unknown Item"


def _parse_character_row(raw: dict) -> CharacterSummary:
    fame_text = raw.get("fame") or ""
    place_text = raw.get("place") or ""
    sprite_x, sprite_y = _parse_background_position(raw.get("char_bg_position"))

    equipment: list[EquipmentItem] = []
    for item in raw.get("equipment") or []:
        item_x, item_y = _parse_background_position(item.get("bg_position"))
        slot_x, slot_y = _parse_background_position(item.get("slot_bg_position"))
        wiki_href = item.get("wiki_href")
        equipment.append(
            EquipmentItem(
                name=_equipment_name_from_tooltip(item.get("tooltip") or "", wiki_href),
                tooltip=item.get("tooltip") or "",
                wiki_url=f"{REALMEYE_BASE}{wiki_href}" if wiki_href else None,
                sprite_sheet_url=_parse_css_url(item.get("bg_image")),
                sprite_x=item_x,
                sprite_y=item_y,
                sprite_size=_parse_css_px(item.get("width")),
                slot_sprite_sheet_url=_parse_css_url(item.get("slot_bg_image")),
                slot_sprite_x=slot_x,
                slot_sprite_y=slot_y,
                slot_sprite_size=_parse_css_px(item.get("slot_width")),
                glow_color=_parse_glow_color(item.get("glow_filter")),
            )
        )

    place_href = raw.get("place_href")
    stats, bonuses = _parse_stat_payload(raw.get("stats_data"))
    if bonuses is None:
        bonuses = _parse_stat_payload(raw.get("stats_bonuses"))[0]
    return CharacterSummary(
        class_name=raw.get("class_name") or "Unknown",
        fame=int(re.sub(r"[^\d]", "", fame_text)) if re.search(r"\d", fame_text) else None,
        place=int(re.sub(r"[^\d]", "", place_text)) if re.search(r"\d", place_text) else None,
        place_url=f"{REALMEYE_BASE}{place_href}" if place_href else None,
        sprite_sheet_url=_parse_css_url(raw.get("char_bg_image")),
        sprite_x=sprite_x,
        sprite_y=sprite_y,
        sprite_width=_parse_css_px(raw.get("char_width")),
        sprite_height=_parse_css_px(raw.get("char_height")),
        stats_maxed=raw.get("stats_text"),
        stats=stats,
        stat_bonuses=bonuses,
        equipment=equipment,
    )


def _parse_exaltation_row(raw: dict) -> ExaltationEntry:
    sprite_x, sprite_y = _parse_background_position(raw.get("char_bg_position"))
    return ExaltationEntry(
        class_name=raw.get("class_name") or "Unknown",
        exaltation_count=_parse_signed_int(raw.get("exaltation_count")),
        max_hp=_parse_signed_int(raw.get("max_hp")),
        max_mp=_parse_signed_int(raw.get("max_mp")),
        attack=_parse_signed_int(raw.get("attack")),
        defense=_parse_signed_int(raw.get("defense")),
        speed=_parse_signed_int(raw.get("speed")),
        dexterity=_parse_signed_int(raw.get("dexterity")),
        vitality=_parse_signed_int(raw.get("vitality")),
        wisdom=_parse_signed_int(raw.get("wisdom")),
        sprite_sheet_url=_parse_css_url(raw.get("char_bg_image")),
        sprite_x=sprite_x,
        sprite_y=sprite_y,
        sprite_width=_parse_css_px(raw.get("char_width")),
        sprite_height=_parse_css_px(raw.get("char_height")),
    )


async def _new_page(browser: Browser) -> Page:
    """Create a page from a context configured to look like a real browser."""
    context = await browser.new_context(
        user_agent=_USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    return await context.new_page()


async def _goto_with_retry(
    page: Page,
    url: str,
    *,
    ready_selector: str,
    timeout: int = 15_000,
    retries: int = 2,
) -> None:
    """
    Navigate with a couple of retries.

    RealmEye fronts pages with a Cloudflare "Just a moment..." interstitial
    that JS-redirects to the real page after a couple seconds. `domcontent
    loaded` fires on that interstitial itself, not the final content, which
    is what made scraping look "randomly" broken | some requests happened to
    land after the redirect, most didn't. Waiting for a selector that only
    exists on the real page (after the redirect) makes this reliable.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            await page.wait_for_selector(ready_selector, timeout=timeout)
            return
        except Exception as e:  # noqa: BLE001 - re-raised as ScraperError below
            last_error = e
            logger.bind(url=url, attempt=attempt, error=str(e)).warning(
                "Navigation attempt failed, retrying" if attempt < retries else "Navigation failed, giving up"
            )
            if attempt < retries:
                await asyncio.sleep(0.75 * attempt)
    raise ScraperError(f"Failed to load {url}: {last_error}")


def _leading_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    match = re.search(r"[\d,]+", text)
    if not match:
        return None
    return int(match.group(0).replace(",", ""))


async def _read_top_pet_from_page(page: Page, username: str) -> Optional[PetInfo]:
    """Pet Yard tab only | skips characters, exaltations, and summary extras."""
    try:
        pet_tab = page.get_by_text("Pet Yard", exact=False)
        if await pet_tab.count() == 0:
            return None
        await pet_tab.first.click(timeout=3000)
        pets: list[dict] = []
        for _ in range(16):
            pets = await page.evaluate(_PET_YARD_JS)
            if pets and any(pet.get("levels") for pet in pets):
                break
            await asyncio.sleep(0.25)
        picked = _pick_top_pet(pets)
        if not picked or picked.get("x") is None or picked.get("y") is None:
            return None
        sheet_match = re.search(r'url\("?([^")]+)"?\)', picked.get("sheet") or "")
        size_match = re.search(r"\d+", picked.get("size") or "")
        top_pet = PetInfo(
            name=picked["name"],
            sprite_sheet_url=sheet_match.group(1) if sheet_match else None,
            sprite_x=int(picked["x"]),
            sprite_y=int(picked["y"]),
            sprite_size=int(size_match.group(0)) if size_match else 48,
        )
        logger.bind(
            username=username,
            pet=top_pet.name,
            levels=picked.get("levels"),
        ).info("Picked top pet by RealmEye ability total")
        return top_pet
    except Exception as e:
        logger.bind(username=username, error=str(e)).warning("Pet sprite lookup failed")
        return None


async def scrape_player_pet(username: str) -> PlayerProfile:
    """Fast sidebar lookup: load the player page, open Pet Yard, return top pet only."""

    async def _run() -> PlayerProfile:
        url = f"{REALMEYE_BASE}/player/{username}"
        logger.bind(username=username, url=url).info("Scraping player pet (compact)")
        async with _playwright_browser() as browser:
            page = await _new_page(browser)
            await _goto_with_retry(page, url, ready_selector="table.summary")
            title = await page.title()
            if "404" in title or "Private" in title.lower():
                raise ScraperError(f"Player '{username}' not found or profile is private")
            top_pet = await _read_top_pet_from_page(page, username)
            if not top_pet:
                raise ScraperError(PET_NOT_FOUND_MSG)
            return PlayerProfile(username=username, top_pet=top_pet)

    try:
        return await asyncio.wait_for(_run(), timeout=PET_LOOKUP_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise ScraperError(PET_NOT_FOUND_MSG) from None
    except PlaywrightTimeout:
        raise ScraperError(PET_NOT_FOUND_MSG) from None


async def _summary_cell(page: Page, label: str) -> Optional[str]:
    """Read a RealmEye summary-table value by exact left-column label."""
    return await page.evaluate(
        """(label) => {
          const want = label.trim().toLowerCase();
          for (const row of document.querySelectorAll("table.summary tr")) {
            const cells = [...row.querySelectorAll("td")];
            if (
              cells.length >= 2 &&
              cells[0].textContent.trim().toLowerCase() === want
            ) {
              return cells[1].textContent.trim();
            }
          }
          return null;
        }""",
        label,
    )


async def scrape_player_profile(username: str) -> PlayerProfile:
    """Scrape a player profile from realmeye.com/player/{username}."""
    url = f"{REALMEYE_BASE}/player/{username}"
    logger.bind(username=username, url=url).info("Scraping player profile")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = await _new_page(browser)
            await _goto_with_retry(page, url, ready_selector="table.summary")

            # Check for private / not found
            title = await page.title()
            if "404" in title or "Private" in title.lower():
                raise ScraperError(f"Player '{username}' not found or profile is private")

            # Fame / Account fame / rank | cells render like "150,868 (1,499th)"
            # or include a star-rank widget, so pull out the leading number.
            # Labels must match exactly: "Fame" is live character fame, and
            # "Account fame" is the in-game dead-fame total.
            fame = None
            account_fame = None
            rank = None
            try:
                fame = _leading_int(await _summary_cell(page, "Fame"))
            except Exception:
                pass
            try:
                account_fame = _leading_int(await _summary_cell(page, "Account fame"))
            except Exception:
                pass
            try:
                rank_el = page.locator("table.summary td:has-text('Rank') + td")
                rank_text = await rank_el.first.inner_text(timeout=3000)
                match = re.search(r"\d+", rank_text)
                if match:
                    rank = int(match.group(0))
            except Exception:
                pass

            # Total exaltation count | same summary table row as fame/rank
            # (e.g. "513 (991st)"), cheap to grab here since it doesn't need
            # the Exaltations tab click. The full per-class breakdown below
            # is a separate, slightly costlier scrape (own AJAX tab).
            total_exaltations = None
            try:
                exalt_el = page.locator("table.summary td:has-text('Exaltations') + td")
                exalt_text = await exalt_el.first.inner_text(timeout=3000)
                match = re.search(r"[\d,]+", exalt_text)
                if match:
                    total_exaltations = int(match.group(0).replace(",", ""))
            except Exception:
                pass

            # Guild
            guild = None
            guild_rank = None
            try:
                guild_el = page.locator("table.summary td:has-text('Guild') + td a")
                guild = await guild_el.first.inner_text(timeout=3000)
                rank_el = page.locator("table.summary td:has-text('Guild Rank') + td")
                guild_rank = await rank_el.first.inner_text(timeout=3000)
            except Exception:
                pass

            # Characters | same story as the pet list: RealmEye lazy-loads
            # this via an AJAX tab click rather than shipping it in the
            # initial HTML. Unlike the pet grid, the populated table shows
            # up immediately after the click (no empty-placeholder race), so
            # a single wait_for is enough | but its id (e.g. "O") is dynamic
            # and not reliable across players/loads, so we match by class
            # instead. Columns (confirmed via live inspection): 0=pet icon,
            # 1=character render, 2=Class, 3=Level, 4=Fame, 5=Placement,
            # 6=Equipment, 7=Stats.
            #
            # We pull the whole table in a single page.evaluate() rather than
            # looping Locator calls per cell/item | with ~7 characters x ~5
            # equipped items each, that'd be 100+ individual round trips.
            characters: list[CharacterSummary] = []
            try:
                char_tab = page.get_by_text("Characters", exact=True)
                if await char_tab.count() > 0:
                    await char_tab.first.click()
                    rows = page.locator("table.tablesorter tbody tr")
                    await rows.first.wait_for(timeout=5000)
                    # `drawCharacters()` recolors portraits asynchronously
                    # (it loads sheets.png itself, composites dye layers onto
                    # a <canvas>, then injects a <style> override) | give it
                    # a chance to finish so we scrape the real colored
                    # portrait instead of the pre-recolor base silhouette.
                    try:
                        await page.wait_for_function(_WAIT_FOR_CHARACTER_COMPOSITE_JS, timeout=8000)
                    except Exception:
                        logger.bind(username=username).warning(
                            "Character portrait recolor didn't finish in time; sprites may look uncolored"
                        )
                    raw_rows = await page.locator("table.tablesorter").first.evaluate(_CHARACTER_TABLE_JS)
                    for raw in raw_rows[:20]:
                        try:
                            characters.append(_parse_character_row(raw))
                        except Exception:
                            continue
            except Exception as e:
                logger.bind(username=username, error=str(e)).warning("Character list scrape failed")

            # Exaltations | a separate lazy-loaded tab/table (same shell as
            # Characters), one row per *class* rather than per character
            # since exaltation bonuses apply to every character of that
            # class. Tab label includes the player's total count, e.g.
            # "Exaltations (513)", hence the partial-text match.
            exaltations: list[ExaltationEntry] = []
            try:
                exalt_tab = page.get_by_text("Exaltations (", exact=False)
                if await exalt_tab.count() > 0:
                    await exalt_tab.first.click()
                    rows = page.locator("table.tablesorter tbody tr")
                    await rows.first.wait_for(timeout=5000)
                    try:
                        await page.wait_for_function(_WAIT_FOR_CHARACTER_COMPOSITE_JS, timeout=8000)
                    except Exception:
                        logger.bind(username=username).warning(
                            "Exaltation portrait recolor didn't finish in time; sprites may look uncolored"
                        )
                    raw_rows = await page.locator("table.tablesorter").first.evaluate(_EXALTATION_TABLE_JS)
                    for raw in raw_rows[:20]:
                        try:
                            exaltations.append(_parse_exaltation_row(raw))
                        except Exception:
                            continue
            except Exception as e:
                logger.bind(username=username, error=str(e)).warning("Exaltation list scrape failed")

            top_pet = await _read_top_pet_from_page(page, username)

            profile = PlayerProfile(
                username=username,
                fame=fame,
                account_fame=account_fame,
                rank=rank,
                guild=guild,
                guild_rank=guild_rank,
                total_exaltations=total_exaltations,
                characters=characters,
                exaltations=exaltations,
                top_pet=top_pet,
                scraped_at=datetime.utcnow(),
            )
            logger.bind(username=username).info("Player profile scraped successfully")
            return profile

        except ScraperError:
            raise
        except PlaywrightTimeout:
            raise ScraperError(f"Timeout scraping player '{username}'")
        except Exception as e:
            logger.bind(username=username).exception("Unexpected error scraping player profile")
            raise ScraperError(f"Failed to scrape player '{username}': {e}") from e
        finally:
            await browser.close()


def _item_wiki_slug(item_name: str) -> str:
    """RealmEye slug: spaces and apostrophes become hyphens, e.g.
    "Angel's Fanfare" -> "angel-s-fanfare"."""
    slug = (item_name or "").strip().lower()
    slug = slug.replace("'", "-").replace("\u2019", "-").replace("\u2018", "-")
    slug = slug.replace(".", "").replace(":", "-").replace(";", "-")
    slug = slug.replace("(", "-").replace(")", "-")
    slug = slug.replace(" ", "-")
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug


_WIKI_TITLE_SUFFIX = re.compile(r"\s*[-–—]\s*the RotMG Wiki.*$", re.IGNORECASE)


def _clean_item_name(name: str) -> str:
    """Page <title>/h1 often appends ' - the RotMG Wiki'; keep just the item."""
    return _WIKI_TITLE_SUFFIX.sub("", (name or "").strip()).strip()


# Pulls one item's wiki header (sprites + flavor text) and infobox in a
# single round trip. Reskin tables are skipped; shiny sprites are kept.
# Rings like The Forgotten Crown put Reskin(s) tables *before* the real
# infobox, so we find the infobox by its first-row label (Tier / On Equip)
# rather than assuming tables[1].
_ITEM_PAGE_JS = """
(root) => {
  const abs = (src) => {
    if (!src) return null;
    return src.startsWith('http') ? src : ('https://www.realmeye.com' + src);
  };
  const cleanName = (s) => (s || '').replace(/\\s*[-–—]\\s*the RotMG Wiki.*$/i, '').trim();
  const cellText = (el) => {
    if (!el) return '';
    const clone = el.cloneNode(true);
    clone.querySelectorAll('br').forEach((br) => br.replaceWith('\\n'));
    const text = clone.innerText.split('\\n').map((l) => l.replace(/\\s+/g, ' ').trim()).filter(Boolean).join('\\n');
    if (text) return text;
    const alts = Array.from(el.querySelectorAll('img'))
      .map((img) => (img.getAttribute('alt') || img.getAttribute('title') || '').trim())
      .filter(Boolean);
    return alts.join(', ');
  };

  const tables = Array.from(root.querySelectorAll('table'));
  const header = tables[0];
  let sprite_url = null;
  let shiny_sprite_url = null;
  let description = '';
  let spriteName = '';
  if (header) {
    const rows = Array.from(header.querySelectorAll('tr'));
    for (const row of rows) {
      const firstTd = row.querySelector('td');
      if (!firstTd) continue;
      const img = firstTd.querySelector('img');
      if (!img) continue;
      const label = ((img.getAttribute('alt') || img.getAttribute('title') || '')).trim();
      const src = abs(img.getAttribute('src'));
      if (/projectile/i.test(label)) continue;
      if (/\\(shiny\\)/i.test(label)) {
        if (!shiny_sprite_url) shiny_sprite_url = src;
      } else if (!sprite_url) {
        sprite_url = src;
        spriteName = cleanName(label.replace(/\\s*\\(shiny\\)\\s*/i, ''));
      }
    }
    const descTd = header.querySelector('td[rowspan]');
    if (descTd) description = descTd.innerText.trim();
  }

  const h1 = root.querySelector('h1');
  const name = cleanName(h1 ? h1.textContent : '') || spriteName;

  const infobox = tables.find((t) => {
    const th = t.querySelector('th');
    if (!th) return false;
    const key = th.innerText.trim();
    return /^(tier|on equip|mp cost)$/i.test(key);
  });
  const stats = {};
  if (infobox) {
    for (const row of infobox.querySelectorAll('tr')) {
      const cells = Array.from(row.querySelectorAll('th, td'));
      if (cells.length < 2) continue;
      const key = cellText(cells[0]).replace(/:$/, '');
      if (!key || /^reskin/i.test(key)) continue;
      const val = cellText(cells[1]);
      if (val) stats[key] = val;
    }
  }

  // Summon / projectile combat tables sit after the item infobox.
  // Grandmaster Mace: "Damage: 275-305 (+5.2 for every WIS above 55)".
  const addStat = (key, val) => {
    if (!key || !val || /^reskin/i.test(key)) return;
    const dest = /^effect/i.test(key) && stats[key] ? ('Summon ' + key) : key;
    if (!stats[dest]) stats[dest] = val;
    else if (stats[dest] !== val) stats[dest] += '; ' + val;
  };
  for (const t of tables) {
    if (t === infobox || t === header) continue;
    const firstKeys = Array.from(t.querySelectorAll('tr')).map((row) => {
      const cells = Array.from(row.querySelectorAll('th, td'));
      return cells.length ? cellText(cells[0]).replace(/:$/, '') : '';
    });
    const isCombat = firstKeys.some((k) =>
      /^(damage|shots|summon lifetime|summon cost|projectile speed|range)$/i.test(k)
    );
    if (!isCombat) continue;
    for (const row of t.querySelectorAll('tr')) {
      const cells = Array.from(row.querySelectorAll('th, td'));
      if (cells.length < 2) continue;
      addStat(cellText(cells[0]).replace(/:$/, ''), cellText(cells[1]));
    }
  }

  const loot = tables.find((t) => {
    const th = t.querySelector('th');
    return th && /^(loot bag|drops from|obtained through)$/i.test(th.innerText.trim());
  });
  const drops = [];
  if (loot) {
    for (const row of loot.querySelectorAll('tr')) {
      const th = row.querySelector('th');
      const td = row.querySelector('td');
      if (!th || !td) continue;
      const key = th.innerText.trim();
      if (/drops from|obtained through/i.test(key)) {
        td.querySelectorAll('a').forEach((a) => {
          const t = a.textContent.trim();
          if (t) drops.push(t);
        });
      }
    }
  }
  const limited = /limited edition/i.test(
    [name, description, JSON.stringify(stats)].join(' ')
  ) || /limited edition item/i.test((root.innerText || '').slice(0, 1800));
  return { name, description, stats, sprite_url, shiny_sprite_url, drops, limited };
}
"""


# Only the Name-column link on dedicated equipment hubs (/wiki/lutes, /wiki/traps).
# Effect cells link status pages like "DEF Decrease" — those are not items.
_ABILITY_HUB_JS = """
(root) => {
  const abs = (href) => {
    if (!href) return null;
    return href.startsWith('http') ? href : ('https://www.realmeye.com' + href);
  };
  const skipSlug = /^(weapons|ability-items|armor|rings|attack-rings|defense-rings|health-rings|magic-rings|speed-rings|dexterity-rings|vitality-rings|wisdom-rings|enchanting|daggers|dual-blades|staves|spellblades|swords|flails|bows|longbows|wands|morning-stars|katanas|tachis|cloaks|quivers|spells|tomes|helms|shields|seals|poisons|skulls|traps|orbs|prisms|scepters|stars|wakizashi|lutes|maces|sheaths|sigils|leather-armors|robes|heavy-armors)$/i;
  const skipName = /^(hp|mp|att|def|spd|dex|vit|wis|attack|defense|speed|dexterity|vitality|wisdom|mana)?[\\s-]*(decrease|increase)$|^amulet of (minor|greater|superior|paramount|exalted|unbound)\\b/i;
  const items = [];
  const seen = new Set();

  const isItemTable = (headers) => {
    const text = headers.join(' ');
    return /\\bname\\b/.test(text) || (/\\btier\\b/.test(text) && /\\b(mp cost|cost|damage|feed|stat bonus|def)\\b/.test(text));
  };

  const nameColumn = (headers) => {
    const exact = headers.findIndex((h) => h === 'name');
    if (exact >= 0) return exact;
    return -1;
  };

  const nameLink = (row, nameIdx) => {
    const cells = Array.from(row.querySelectorAll(':scope > th, :scope > td'));
    if (nameIdx >= 0 && cells[nameIdx]) {
      const a = cells[nameIdx].querySelector('a[href*="/wiki/"]');
      if (a) return a;
    }
    for (const cell of cells) {
      if (cell.querySelector('img') && cell.querySelector('a[href*="/wiki/"]')) {
        return cell.querySelector('a[href*="/wiki/"]');
      }
    }
    return null;
  };

  for (const table of root.querySelectorAll('table')) {
    const headerRow = table.querySelector('tr');
    if (!headerRow) continue;
    const headers = Array.from(headerRow.querySelectorAll('th, td')).map(
      (c) => c.innerText.replace(/\\s+/g, ' ').trim().toLowerCase()
    );
    if (!isItemTable(headers)) continue;
    let walk = table.previousElementSibling;
    let limitedSection = false;
    for (let i = 0; i < 12 && walk; i++) {
      const t = (walk.innerText || '').replace(/\\s+/g, ' ').trim();
      const tag = (walk.tagName || '').toLowerCase();
      if (/limited edition/i.test(t)) { limitedSection = true; break; }
      if (/^h[1-4]$/.test(tag) && t) break;
      walk = walk.previousElementSibling;
    }
    if (limitedSection) continue;
    const nameIdx = nameColumn(headers);
    const bonusIdx = headers.findIndex((h) => /stat bonus|on equip|^bonus$/.test(h));
    const tierIdx = headers.findIndex((h) => h === 'tier');
    const statIdx = {};
    headers.forEach((h, i) => {
      const map = {
        hp: 'HP', mp: 'MP', att: 'Attack', attack: 'Attack',
        def: 'Defense', defense: 'Defense', spd: 'Speed', speed: 'Speed',
        dex: 'Dexterity', dexterity: 'Dexterity', vit: 'Vitality',
        vitality: 'Vitality', wis: 'Wisdom', wisdom: 'Wisdom',
      };
      if (map[h]) statIdx[map[h]] = i;
    });

    for (const row of Array.from(table.querySelectorAll('tr')).slice(1)) {
      const cells = Array.from(row.querySelectorAll(':scope > th, :scope > td'));
      const rowText = row.innerText.replace(/\\s+/g, ' ').trim();
      const tierCell = (tierIdx >= 0 && cells[tierIdx])
        ? cells[tierIdx].innerText.replace(/\\s+/g, ' ').trim()
        : '';
      let tier = '';
      const named = `${tierCell} ${rowText}`.match(/\\b(UT\\+?|ST|L|T[0-7])\\b/i);
      if (named) {
        tier = named[1].toUpperCase();
      } else {
        const bare = tierCell.match(/^([0-7])$/);
        if (bare) tier = 'T' + bare[1];
      }
      const a = nameLink(row, nameIdx);
      if (!a) continue;
      const href = a.getAttribute('href') || '';
      const slug = (href.split('/wiki/')[1] || '').split('#')[0].split('?')[0];
      const name = (a.textContent || '').replace(/\\s+/g, ' ').trim();
      if (!slug || !name || name.length < 3) continue;
      if (skipSlug.test(slug) || skipName.test(name)) continue;
      const key = name.toLowerCase();
      if (seen.has(key)) continue;
      const bonus = (bonusIdx >= 0 && cells[bonusIdx])
        ? cells[bonusIdx].innerText.replace(/\\s+/g, ' ').trim()
        : '';
      const statValues = {};
      Object.entries(statIdx).forEach(([stat, i]) => {
        const n = parseInt((cells[i] && cells[i].innerText || '').replace(/[^0-9-]/g, ''), 10);
        if (!Number.isNaN(n)) statValues[stat] = n;
      });
      if (!tier) {
        if (bonus || Object.keys(statValues).length) tier = 'UT';
        else continue;
      }
      seen.add(key);
      items.push({
        name,
        slug,
        href: abs(href),
        tier,
        rowText,
        bonus,
        statValues,
      });
    }
  }
  return items;
}
"""


def _item_from_raw(raw: dict, fallback_name: str, url: str) -> ItemProfile:
    stats = raw.get("stats") or {}
    title = _clean_item_name(raw.get("name") or fallback_name)
    return ItemProfile(
        name=title or fallback_name.strip(),
        tier=stats.get("Tier"),
        description=(raw.get("description") or "").strip() or None,
        stats=stats,
        sprite_url=raw.get("sprite_url"),
        shiny_sprite_url=raw.get("shiny_sprite_url"),
        drop_locations=raw.get("drops") or [],
        wiki_url=url,
        limited_edition=bool(raw.get("limited")),
    )


async def scrape_ability_hub(slug: str) -> list[dict]:
    """Item names from a dedicated hub such as /wiki/lutes or /wiki/traps.

    Only the Name column (or sprite+name cell) is used. Effect links like
    DEF Decrease are ignored.
    """
    url = f"{REALMEYE_BASE}/wiki/{slug}"
    logger.bind(slug=slug, url=url).info("Scraping ability hub")
    async with _playwright_browser() as browser:
        try:
            page = await _new_page(browser)
            await _goto_with_retry(page, url, ready_selector=".wiki-page")
            raw = await page.locator(".wiki-page").first.evaluate(_ABILITY_HUB_JS)
            return list(raw or [])
        except ScraperError:
            raise
        except Exception as e:
            logger.bind(slug=slug).exception("Error scraping ability hub")
            raise ScraperError(f"Failed to scrape ability hub '{slug}': {e}") from e


async def scrape_items_batch(names: list[str]) -> list[ItemProfile]:
    """Scrape several item wiki pages in one browser session."""
    if not names:
        return []
    profiles: list[ItemProfile] = []
    async with _playwright_browser() as browser:
        page = await _new_page(browser)
        for item_name in names:
            url = f"{REALMEYE_BASE}/wiki/{_item_wiki_slug(item_name)}"
            logger.bind(item_name=item_name, url=url).info("Scraping item")
            try:
                await _goto_with_retry(
                    page, url, ready_selector=".wiki-page", timeout=8_000, retries=2
                )
                title = _clean_item_name((await page.title()).split("|")[0].strip())
                if "404" in title:
                    continue
                raw = await page.locator(".wiki-page").first.evaluate(_ITEM_PAGE_JS)
                profiles.append(_item_from_raw(raw, item_name, url))
            except Exception as e:
                logger.bind(item_name=item_name, error=str(e)).warning(
                    "Skipping item during batch scrape"
                )
                try:
                    page = await _new_page(browser)
                except Exception:
                    break
    return profiles


async def scrape_item(item_name: str) -> ItemProfile:
    """Scrape a single item's RealmEye wiki page into a structured profile."""
    slug = _item_wiki_slug(item_name)
    url = f"{REALMEYE_BASE}/wiki/{slug}"
    logger.bind(item_name=item_name, url=url).info("Scraping item")

    async with _playwright_browser() as browser:
        try:
            page = await _new_page(browser)
            await _goto_with_retry(page, url, ready_selector=".wiki-page")

            title = _clean_item_name((await page.title()).split("|")[0].strip())
            if "404" in title:
                raise ScraperError(f"Item '{item_name}' not found")

            raw = await page.locator(".wiki-page").first.evaluate(_ITEM_PAGE_JS)
            return _item_from_raw(raw, item_name, url)

        except ScraperError:
            raise
        except Exception as e:
            logger.bind(item_name=item_name).exception("Error scraping item")
            raise ScraperError(f"Failed to scrape item '{item_name}': {e}") from e


DUNGEON_INDEX_SLUGS = ("dungeon-guides", "dungeons")

# Pull dungeon/guide targets from the official RealmEye indexes.
# dungeon-guides is a grid of *-guide links; dungeons lists each dungeon
# as the first link in a table row. Other columns (keys, enemies) are ignored.
_DUNGEON_INDEX_JS = """
(root) => {
  const scope = root || document.body;
  const skip = /^(dungeons|dungeon-guides|dungeon-keys|dungeon-modifiers|dungeon-collection|release-history)(?:$|#)/i;
  const seen = new Set();
  const out = [];

  const add = (a) => {
    if (!a) return;
    const href = a.getAttribute('href') || '';
    const m = href.match(/\\/wiki\\/([^?#]+)/i);
    if (!m) return;
    let slug = m[1];
    try { slug = decodeURIComponent(slug); } catch (e) { /* keep raw */ }
    slug = slug.toLowerCase();
    if (!slug || skip.test(slug) || slug.includes(':') || seen.has(slug)) return;
    let title = (a.textContent || '').replace(/\\s+/g, ' ').trim();
    if (title.length < 3) {
      const img = a.querySelector('img');
      title = ((img && (img.getAttribute('alt') || img.getAttribute('title'))) || '')
        .replace(/\\s+/g, ' ').trim();
    }
    if (title.length < 3) {
      title = slug.replace(/-guide$/, '').replace(/-/g, ' ');
    }
    if (/^(portal|key)$/i.test(title) || /\\bkey$/i.test(title)) return;
    seen.add(slug);
    out.push({
      title,
      slug,
      kind: slug.endsWith('-guide') ? 'guide' : 'dungeon',
      portal_url: null,
      difficulty: null,
    });
  };

  const abs = (src) => {
    if (!src) return null;
    if (src.startsWith('http')) return src;
    if (src.startsWith('//')) return 'https:' + src;
    return src.startsWith('/') ? ('https://www.realmeye.com' + src) : src;
  };

  for (const a of scope.querySelectorAll('a[href*="/wiki/"]')) {
    const href = a.getAttribute('href') || '';
    if (/\\/wiki\\/[^?#]+-guide(?:$|[?#])/i.test(href)) add(a);
  }
  for (const row of scope.querySelectorAll('table tr')) {
    const cells = Array.from(row.querySelectorAll(':scope > td'));
    const first = cells[0] || row.querySelector('td, th');
    const a = first && first.querySelector('a[href*="/wiki/"]');
    if (a) add(a);
    if (!a || cells.length < 2) continue;
    const href = a.getAttribute('href') || '';
    const slugM = href.match(/\\/wiki\\/([^?#]+)/i);
    if (!slugM) continue;
    let slug = slugM[1];
    try { slug = decodeURIComponent(slug); } catch (e) { /* keep */ }
    slug = slug.toLowerCase();
    const entry = out.find((e) => e.slug === slug);
    if (!entry) continue;
    const portalImg = (cells[1] && cells[1].querySelector('img')) || first.querySelector('img');
    if (portalImg && !entry.portal_url) entry.portal_url = abs(portalImg.getAttribute('src'));
    const last = cells[cells.length - 1];
    const diff = ((last && last.innerText) || '').trim().match(/^(\\d+(?:\\.\\d+)?)$/);
    if (diff) entry.difficulty = Number(diff[1]);
  }
  return out;
}
"""


async def scrape_dungeon_indexes() -> list[dict]:
    """Scrape /wiki/dungeon-guides and /wiki/dungeons for dungeon page links."""
    merged: dict[str, dict] = {}
    async with _playwright_browser() as browser:
        page = await _new_page(browser)
        for slug in DUNGEON_INDEX_SLUGS:
            url = f"{REALMEYE_BASE}/wiki/{slug}"
            logger.bind(slug=slug, url=url).info("Scraping dungeon index")
            try:
                await _goto_with_retry(page, url, ready_selector=".wiki-page")
                if slug == "dungeon-guides":
                    try:
                        await page.wait_for_selector(
                            'a[href*="-guide"]', timeout=8_000
                        )
                    except Exception:
                        pass
                raw = await page.locator(".wiki-page").first.evaluate(_DUNGEON_INDEX_JS)
                logger.bind(slug=slug, links=len(raw or [])).info(
                    "Dungeon index links extracted"
                )
                for item in raw or []:
                    key = (item.get("slug") or "").strip()
                    if not key:
                        continue
                    prev = merged.get(key)
                    if not prev or (
                        item.get("kind") == "guide" and prev.get("kind") != "guide"
                    ):
                        merged[key] = {
                            "title": item.get("title") or key,
                            "slug": key,
                            "kind": item.get("kind") or "dungeon",
                            "source": slug,
                            "portal_url": item.get("portal_url"),
                            "difficulty": item.get("difficulty"),
                        }
                    elif prev:
                        if item.get("portal_url") and not prev.get("portal_url"):
                            prev["portal_url"] = item.get("portal_url")
                        if item.get("difficulty") is not None and prev.get("difficulty") is None:
                            prev["difficulty"] = item.get("difficulty")
            except ScraperError:
                logger.bind(slug=slug).warning("Dungeon index page unavailable")
            except Exception as e:
                logger.bind(slug=slug, error=str(e)).warning(
                    "Dungeon index scrape failed"
                )
    if not merged:
        raise ScraperError("Failed to scrape RealmEye dungeon indexes")
    logger.bind(links=len(merged)).info("Scraped RealmEye dungeon index links")
    return list(merged.values())


_DUNGEON_PAGE_JS = """
(root) => {
  const abs = (src) => {
    if (!src) return null;
    if (src.startsWith('http')) return src;
    if (src.startsWith('//')) return 'https:' + src;
    return src.startsWith('/') ? ('https://www.realmeye.com' + src) : src;
  };
  const headingBefore = (el) => {
    let node = el;
    for (let i = 0; i < 14 && node; i++) {
      let prev = node.previousElementSibling;
      while (prev) {
        if (/^H[1-6]$/.test(prev.tagName)) return (prev.textContent || '').trim();
        prev = prev.previousElementSibling;
      }
      node = node.parentElement;
    }
    return '';
  };
  const skipImg = (alt, src) => {
    if (!src) return true;
    if (/favicon|logo|discord|paypal|button|static\\/img\\/(?:header|nav)/i.test(src)) return true;
    if (/^difficulty$/i.test(alt || '')) return true;
    return false;
  };

  let portal_url = null;
  let difficulty = null;
  let graves_url = null;
  for (const img of root.querySelectorAll('img')) {
    const alt = (img.getAttribute('alt') || img.getAttribute('title') || '').trim();
    const src = abs(img.getAttribute('src'));
    if (/portal/i.test(alt) && src && !portal_url && !/(ice|fire|stone)\\s*portal/i.test(alt)) {
      portal_url = src;
    }
  }
  const tables = Array.from(root.querySelectorAll('table'));
  const infoTable = tables[0];
  if (infoTable) {
    let graveCount = 0;
    for (const img of infoTable.querySelectorAll('img')) {
      const alt = (img.getAttribute('alt') || img.getAttribute('title') || '').trim();
      const src = abs(img.getAttribute('src'));
      if (skipImg(alt, src)) continue;
      const labeled = alt.match(/difficulty:\\s*(\\d+(?:\\.\\d+)?)/i);
      if (labeled) {
        difficulty = Number(labeled[1]);
        if (!graves_url && src) graves_url = src;
        graveCount++;
      }
    }
    if (difficulty == null && graveCount >= 1 && graveCount <= 10) {
      difficulty = graveCount;
    }
  }
  if (!portal_url && tables[0]) {
    const firstImg = tables[0].querySelector('img');
    const tableAlt = (firstImg && (firstImg.getAttribute('alt') || firstImg.getAttribute('title') || '')) || '';
    if (firstImg && !/(ice|fire|stone)\\s*portal/i.test(tableAlt)) {
      portal_url = abs(firstImg.getAttribute('src'));
    }
  }
  if (difficulty == null) {
    const blob = root.innerText || '';
    const m = blob.match(/Difficulty[^\\d]{0,40}(\\d+(?:\\.\\d+)?)\\s*\\/\\s*10/i)
      || blob.match(/Difficulty[^\\d]{0,24}(\\d+(?:\\.\\d+)?)/i);
    if (m) difficulty = Number(m[1]);
  }

  const layouts = [];
  const seenLayout = new Set();
  for (const img of root.querySelectorAll('img')) {
    const src = abs(img.getAttribute('src'));
    const alt = (img.getAttribute('alt') || img.getAttribute('title') || '').trim();
    if (skipImg(alt, src) || seenLayout.has(src)) continue;
    const head = headingBefore(img);
    if (/layout|example layout|minimap|\\bmap\\b/i.test(alt + ' ' + head)) {
      seenLayout.add(src);
      layouts.push({ caption: alt || head || 'Example Layout', url: src });
    }
  }

  const drops = [];
  const seenDrop = new Set();
  let dropTable = null;
  for (const h of root.querySelectorAll('h1,h2,h3,h4,h5')) {
    if (!/drops of interest|notable drops/i.test(h.textContent || '')) continue;
    let n = h.nextElementSibling;
    while (n && !/^H[1-2]$/.test(n.tagName)) {
      if (n.matches && n.matches('table')) { dropTable = n; break; }
      const inner = n.querySelector && n.querySelector('table');
      if (inner) { dropTable = inner; break; }
      n = n.nextElementSibling;
    }
    break;
  }
  if (dropTable) {
    const skipName = /dungeon-keys|(?:^|\\s)key$|\\bpotion\\b|^tier\\s+\\d+\\s+|(?:pet\\s+)?skins?$|sage genji|drummer kaguya|dancer miko|kitsune umi|village girl umi|umi, goddess/i;
    const headerCells = Array.from(
      (dropTable.querySelector('tr') || { querySelectorAll: () => [] }).querySelectorAll('th,td')
    );
    let fromIdx = 1;
    headerCells.forEach((c, i) => {
      if (/drops from|dropped by/i.test(c.innerText || '')) fromIdx = i;
    });
    for (const row of dropTable.querySelectorAll('tr')) {
      const cells = Array.from(row.querySelectorAll(':scope > td'));
      if (!cells.length) continue;
      const cell = cells[0];
      const fromCell = cells[fromIdx] || cells[1];
      const dropsFrom = ((fromCell && fromCell.innerText) || '').replace(/\\s+/g, ' ').trim();
      const pushDrop = (name, img, wikiSlug) => {
        const key = name.toLowerCase();
        if (!key || skipName.test(name)) return;
        if (seenDrop.has(key)) {
          const prev = drops.find((d) => (d.name || '').toLowerCase() === key);
          if (prev && dropsFrom) {
            const have = new Set((prev.drops_from || '').split(/,\\s*/).map((s) => s.toLowerCase()));
            const extra = dropsFrom.split(/,\\s*/).filter((s) => s && !have.has(s.toLowerCase()));
            if (extra.length) {
              prev.drops_from = [prev.drops_from, extra.join(', ')].filter(Boolean).join(', ');
            }
          }
          if (prev && !prev.sprite_url && img) {
            prev.sprite_url = abs(img.getAttribute('src'));
          }
          return;
        }
        seenDrop.add(key);
        drops.push({
          name,
          sprite_url: img ? abs(img.getAttribute('src')) : null,
          wiki_slug: wikiSlug || null,
          drops_from: dropsFrom || null,
        });
      };
      let linked = false;
      for (const a of cell.querySelectorAll('a[href*="/wiki/"]')) {
        const img = a.querySelector('img') || cell.querySelector('img');
        const href = a.getAttribute('href') || '';
        const slugM = href.match(/\\/wiki\\/([^?#]+)/);
        const name = (
          (a.textContent || '').trim()
          || (a.getAttribute('title') || '')
          || (img && (img.getAttribute('alt') || img.getAttribute('title') || ''))
          || (slugM ? slugM[1].replace(/-/g, ' ') : '')
        ).replace(/\\s+/g, ' ').trim();
        if (href.includes('#') && /stat-increase|enchanting/i.test(href)) continue;
        linked = true;
        pushDrop(name, img, slugM ? slugM[1] : null);
      }
      if (!linked) {
        const img = cell.querySelector('img');
        const name = (cell.innerText || '').replace(/\\s+/g, ' ').trim().split(/[,\\n]/)[0].trim();
        pushDrop(name, img, null);
      }
    }
  }

  if (!portal_url) {
    for (const img of root.querySelectorAll('img')) {
      const src = abs(img.getAttribute('src'));
      const alt = (img.getAttribute('alt') || '').trim();
      if (skipImg(alt, src) || seenLayout.has(src)) continue;
      if (/\\/s\\/a\\/img\\/wiki/i.test(src || '')) { portal_url = src; break; }
    }
  }
  return { portal_url, difficulty, graves_url, layouts, drops };
}
"""


async def scrape_wiki_article(slug: str) -> dict:
    """Scrape a RealmEye wiki article plus portal, graves, layouts, and drops."""
    url = f"{REALMEYE_BASE}/wiki/{slug}"
    logger.bind(slug=slug, url=url).info("Scraping wiki page")

    async with _playwright_browser() as browser:
        try:
            page = await _new_page(browser)
            await _goto_with_retry(
                page, url, ready_selector=".wiki-page, #mw-content-text, main"
            )

            title = (await page.title()).split("|")[0].strip()
            if "404" in title:
                raise ScraperError(f"Wiki page '{slug}' not found")

            content_el = page.locator(".wiki-page, #mw-content-text, main").first
            try:
                text = await content_el.inner_text(timeout=5000)
            except Exception:
                text = await page.locator("body").inner_text(timeout=5000)

            media: dict = {}
            try:
                media = await content_el.evaluate(_DUNGEON_PAGE_JS)
            except Exception as e:
                logger.bind(slug=slug, error=str(e)).warning(
                    "Dungeon page sprites could not be extracted"
                )

            return {
                "title": title,
                "text": (text or "").strip(),
                "url": url,
                "portal_url": (media or {}).get("portal_url"),
                "difficulty": (media or {}).get("difficulty"),
                "graves_url": (media or {}).get("graves_url"),
                "layouts": list((media or {}).get("layouts") or []),
                "drops": list((media or {}).get("drops") or []),
            }

        except ScraperError:
            raise
        except Exception as e:
            logger.bind(slug=slug).exception("Error scraping wiki page")
            raise ScraperError(f"Failed to scrape wiki page '{slug}': {e}") from e


async def scrape_wiki_page(slug: str) -> tuple[str, str, str]:
    """Title, plain text, and URL for RAG ingestion."""
    article = await scrape_wiki_article(slug)
    return article["title"], article["text"], article["url"]


_ENCHANT_PAGE_JS = """() => {
  const root = document.querySelector('.wiki-page, #mw-content-text, main') || document.body;
  const tables = [];
  let heading = '';
  let subheading = '';
  for (const el of root.querySelectorAll('h2, h3, h4, table')) {
    const tag = (el.tagName || '').toUpperCase();
    if (tag === 'H2' || tag === 'H3' || tag === 'H4') {
      const title = (el.innerText || '').replace(/\\[edit.*?\\]/gi, '').replace(/back to top/gi, '').trim();
      if (tag === 'H2') { heading = title; subheading = ''; }
      else subheading = title;
      continue;
    }
    const rows = [...el.querySelectorAll('tr')].map((tr) =>
      [...tr.querySelectorAll('th, td')].map((c) =>
        (c.innerText || '').replace(/\\s+/g, ' ').trim()
      ).filter((c) => c)
    ).filter((r) => r.length);
    if (rows.length) {
      tables.push({
        heading: [heading, subheading].filter(Boolean).join(' / '),
        rows,
      });
    }
  }
  const paras = [...root.querySelectorAll('p')].map((p) => (p.innerText || '').trim()).filter(Boolean);
  return { tables, overview: paras.slice(0, 6).join('\\n\\n') };
}
"""


async def scrape_enchanting_page() -> dict:
    """RealmEye /wiki/enchanting tables: name, eligible slot, tiered effects."""
    url = f"{REALMEYE_BASE}/wiki/enchanting"
    logger.bind(url=url).info("Scraping RealmEye enchanting tables")
    async with _playwright_browser() as browser:
        try:
            page = await _new_page(browser)
            await _goto_with_retry(
                page, url, ready_selector=".wiki-page, #mw-content-text, main"
            )
            title = (await page.title()).split("|")[0].strip()
            if "404" in title:
                raise ScraperError("Wiki page 'enchanting' not found")
            payload = await page.locator(
                ".wiki-page, #mw-content-text, main"
            ).first.evaluate(_ENCHANT_PAGE_JS)
            return {
                "title": title or "Enchanting",
                "url": url,
                "overview": (payload or {}).get("overview") or "",
                "tables": list((payload or {}).get("tables") or []),
            }
        except ScraperError:
            raise
        except Exception as e:
            logger.exception("Error scraping enchanting wiki")
            raise ScraperError(f"Failed to scrape wiki page 'enchanting': {e}") from e


async def scrape_umi_bis(class_name: str) -> tuple[str, str]:
    """Community best-in-slot page for a class. Stats still come from RealmEye."""
    slug = class_name.strip().lower()
    url = f"{UMI_BASE}/guides/best-in-slot/{slug}?tab=general"
    logger.bind(class_name=class_name, url=url).info("Scraping UmiEnjoyers BIS")
    async with _playwright_browser() as browser:
        page = await _new_page(browser)
        await _goto_with_retry(page, url, ready_selector="main, article, body", timeout=20_000)
        try:
            text = await page.locator("main, article").first.inner_text(timeout=8000)
        except Exception:
            text = await page.locator("body").inner_text(timeout=8000)
        cleaned = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
        if len(cleaned) > 10_000:
            cleaned = cleaned[:10_000] + "\n…"
        return cleaned, url


# RealmEye's outfit chooser (top-characters-with-dyes.js) lists every class
# skin plus Clothing Dye / Large * Cloth and Accessory Dye / Small * Cloth.
# Portraits are not those undyed chooser tiles: characters.js drawCharacters()
# takes the base skin, then paints data-dye1 onto the clothing mask and
# data-dye2 onto the accessory mask. Player rows expose both the packed dye
# values (data-dye1/dye2) and the item ids used in the URL
# (data-clothing-dye-id / data-accessory-dye-id).
_OUTFIT_PAGE = f"{REALMEYE_BASE}/top-characters-with-outfit"

_OUTFIT_CATALOG_JS = """() => {
  const classes = (window.classInfos || []).map((c) => ({
    id: c[0],
    name: c[1],
    skins: (c[6] || []).map((s) => ({ id: s[0], name: s[1] })),
  }));
  const clothing = [];
  const accessory = [];
  const sheet = "https://www.realmeye.com/s/ht/img/renders.png";
  for (const [id, item] of Object.entries(window.items || {})) {
    const name = item && item[0];
    if (typeof name !== "string") continue;
    const row = {
      id: Number(id),
      name,
      sprite_x: Number(item[3]) || 0,
      sprite_y: Number(item[4]) || 0,
      sprite_sheet_url: sheet,
    };
    if (/Clothing Dye$/i.test(name) || /^Large\\b.*\\bCloth$/i.test(name)) {
      clothing.push(row);
    } else if (/Accessory Dye$/i.test(name) || /^Small\\b.*\\bCloth$/i.test(name)) {
      accessory.push(row);
    }
  }
  return { classes, clothing, accessory };
}"""

_COMPOSITE_PORTRAIT_JS = """async (p) => {
  const packedFor = (itemId) => {
    if (!itemId) return 0;
    const y = {};
    Object.keys(window.sheetOffsets || {}).forEach((key) => {
      (window.sheetOffsets[key] || []).slice(4).forEach((extra) => {
        y[extra] = parseInt(key, 10);
      });
    });
    return y[itemId] || itemId;
  };
  const classId = p.classId;
  const skinId = p.skinId;
  const dye1 = packedFor(p.clothingId);
  const dye2 = packedFor(p.accessoryId);

  document.querySelectorAll("a.character, .private-character").forEach((el) => el.remove());
  const el = document.createElement("a");
  el.id = "skin-viz";
  el.className = "character";
  el.setAttribute("data-class", String(classId));
  el.setAttribute("data-skin", String(skinId));
  el.setAttribute("data-dye1", String(dye1));
  el.setAttribute("data-dye2", String(dye2));
  el.style.cssText = "display:block;width:50px;height:50px;";
  document.body.appendChild(el);

  if (typeof drawCharacters !== "function") {
    throw new Error("drawCharacters is not loaded");
  }
  drawCharacters();

  const sheetUri = await new Promise((resolve, reject) => {
    const start = Date.now();
    const tick = () => {
      const bg = getComputedStyle(el).backgroundImage || "";
      const match = bg.match(/url\\(["']?(data:image\\/png;base64,[^"')]+)["']?\\)/);
      if (match) {
        resolve(match[1]);
        return;
      }
      if (Date.now() - start > 12000) {
        reject(new Error("character composite timed out"));
        return;
      }
      requestAnimationFrame(tick);
    };
    setTimeout(tick, 50);
  });

  const parts = (getComputedStyle(el).backgroundPosition || "0 0").split(/\\s+/);
  const x = Math.abs(parseInt(parts[0], 10) || 0);
  const y = Math.abs(parseInt(parts[1], 10) || 0);
  const img = new Image();
  await new Promise((resolve, reject) => {
    img.onload = resolve;
    img.onerror = () => reject(new Error("composite image failed to load"));
    img.src = sheetUri;
  });
  const size = 50;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(img, x, y, size, size, 0, 0, size, size);
  return canvas.toDataURL("image/png");
}"""

_OUTFIT_SCRIPTS_READY_JS = """() => Boolean(
  window.classInfos && window.items && window.sheetOffsets && typeof drawCharacters === "function"
)"""


async def _open_outfit_page(page: Page, class_id: Optional[int] = None, skin_id: Optional[int] = None) -> None:
    if class_id:
        url = f"{_OUTFIT_PAGE}/{class_id}/{skin_id or 0}//"
    else:
        url = _OUTFIT_PAGE
    # `.chooser-table` (previously part of this OR selector) has a
    # permanent zero-height bounding box on RealmEye's live markup - it's a
    # CSS-collapsed container, not a transient loading state (confirmed via
    # a live DOM inspection Sep 14: width 685px, height 0px, immediately and
    # indefinitely). Playwright's default `visible` wait requires a
    # non-empty box, so `wait_for_selector(".chooser-table, #class")`
    # deterministically locked onto whichever of the two matched first in
    # DOM order (`.chooser-table`) and then timed out waiting forever for
    # an element that will never satisfy "visible". `#class` (the "Choose
    # a class" button) is a real, always-visible element and is sufficient
    # on its own - it exists on both URL variants this function uses. The
    # actual data-readiness check already happens next via
    # `_OUTFIT_SCRIPTS_READY_JS`, this selector wait only needs to confirm
    # we're past Cloudflare's interstitial onto the real page.
    await _goto_with_retry(page, url, ready_selector="#class", timeout=20_000)
    await page.wait_for_function(_OUTFIT_SCRIPTS_READY_JS, timeout=15_000)


async def scrape_outfit_catalog() -> dict:
    """Class/skin ids and clothing/accessory dye items from RealmEye's chooser."""
    logger.info("Scraping RealmEye outfit catalog")
    async with _playwright_browser() as browser:
        page = await _new_page(browser)
        try:
            await _open_outfit_page(page)
            catalog = await page.evaluate(_OUTFIT_CATALOG_JS)
        except Exception as e:
            raise ScraperError(f"Failed to scrape outfit catalog: {e}") from e
        finally:
            await page.context.close()
    if not catalog or not catalog.get("classes"):
        raise ScraperError("Outfit catalog was empty")
    return catalog


async def composite_character_portrait(
    class_id: int,
    skin_id: int,
    clothing_id: int = 0,
    accessory_id: int = 0,
) -> str:
    """
    Run RealmEye's drawCharacters() on a dummy portrait: base skin, then
    clothing dye (data-dye1) and accessory dye (data-dye2). Returns a PNG data URI.
    """
    logger.bind(
        class_id=class_id, skin_id=skin_id,
        clothing_id=clothing_id, accessory_id=accessory_id,
    ).info("Compositing character portrait")
    async with _playwright_browser() as browser:
        page = await _new_page(browser)
        try:
            await _open_outfit_page(page, class_id, skin_id)
            data_uri = await page.evaluate(
                _COMPOSITE_PORTRAIT_JS,
                {
                    "classId": class_id,
                    "skinId": skin_id,
                    "clothingId": clothing_id or 0,
                    "accessoryId": accessory_id or 0,
                },
            )
        except Exception as e:
            raise ScraperError(f"Failed to composite character portrait: {e}") from e
        finally:
            await page.context.close()
    if not data_uri or not str(data_uri).startswith("data:image/png"):
        raise ScraperError("Character portrait composite did not return a PNG")
    return str(data_uri)
