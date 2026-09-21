export interface ChangelogEntry {
  /** Sortable id, also shown nowhere. Just needs to be unique and newest-first. */
  version: string;
  /** Human date shown in the UI, e.g. "Sep 13, 2026". */
  date: string;
  /**
   * When this entry actually shipped, ISO 8601 with offset. Powers the
   * "What's new" modal's expanded timeline view (real ship time next to
   * the version badge, so same-day releases like "-2"/"-3" read in order).
   * Backfilled from the git commit that last touched each entry below;
   * never hand-wave a time for a new entry, pull it from `git log` once
   * the change is actually committed.
   */
  timestamp?: string;
  /**
   * True for a labeled era, not a ship date. The timeline shows `date` as a
   * heading and hides the version badge.
   */
  phase?: boolean;
  /** Short, plain-language, user-facing bullets. See .cursor/rules/changelog.mdc. */
  items: string[];
}

/**
 * User-facing changelog, newest entry first. Every deploy that changes what
 * a user can see or do should add (or extend) an entry here. See
 * .cursor/rules/changelog.mdc for the house style.
 */
export const CHANGELOG: ChangelogEntry[] = [
  {
    version: "2026.09.21",
    date: "Sep 21, 2026",
    items: [
      "Pal now reads official RotMG Hub patch notes, so event calendars and new items match what DECA posted.",
      "Asking for a shiny divine item, including awakened, now shows the framed sprite instead of a text apology.",
      "You can upload a sprite and ask to see it as Uncommon, Rare, Legendary, or Divine, including shiny, with the same glow and diamonds as a set preview.",
      "Asking to see the same set, or a player's worn gear, as Divine now keeps those exact items in the four slots.",
    ],
  },
  {
    version: "2026.09.18",
    date: "Sep 18, 2026",
    items: [
      "The DPS specialist is now live. Ask for a class ceiling or a named character and you will get dummy numbers you can check in the guild hall.",
      "Signing in no longer fails to save your chats.",
      "A follow-up like Break it down on a DPS answer now keeps the same depth as the first answer.",
      "A named-player DPS reply now shows only that one character, not fame or the rest of the account.",
      "A DPS breakdown now walks every worn piece, and a stat-tradeoff enchant only changes the numbers those stats actually feed.",
      "Wis and Vit class builds now name the abilities that actually scale with those stats, instead of saying the class has none.",
      "Asking for a Hardmode Shatters guide no longer pretends RealmEye has no page for it.",
      "Wis class builds no longer recommend a T7 katana as the weapon.",
      "Asking for a different class build no longer repeats the last answer.",
      "Class builds wait until the ability list is ready, so they do not skip the scaling ability.",
      "The upgrade preview now includes a DPS demo between set-building and the visualizer.",
    ],
  },
  {
    version: "2026.09.17-16",
    date: "Sep 17, 2026",
    items: [
      "Asking for a player's DPS now attaches the same character card as a player lookup, with item hovers that show on-character enchants, so the reply can stay on the numbers.",
      "Those on-character enchants are now counted in the dummy figure, including when the tooltip is a single line or the prompt names them.",
    ],
  },
  {
    version: "2026.09.17-15",
    date: "Sep 17, 2026",
    items: [
      "A dummy DPS figure now uses only the debuffs that character's own gear inflicts, so a Huntress trap's Curse is not copied onto a Bard in the same chat.",
      "When Attack or Dexterity differs from the character sheet, the answer names every item that moved it, so both on-ability boosts are visible.",
    ],
  },
  {
    version: "2026.09.17-14",
    date: "Sep 17, 2026",
    items: [
      "DPS answers now also give the damage you would see testing alone on the guild hall dummy, next to the fully buffed number, so you can check it against your own game.",
      "Enemy defense is now taken off each shot, so fast multi-shot weapons are no longer overrated.",
      "Shots that ignore defense are now tracked per shot, so a summon's piercing no longer inflates the weapon it came with.",
    ],
  },
  {
    version: "2026.09.17-13",
    date: "Sep 17, 2026",
    items: [
      "DPS for weapons that fire two kinds of shot at different speeds is now correct. Some, like Makakoyumi, were badly understated.",
      "A player's DPS answer now lists that character's eight stats, so you can see exactly what was measured.",
      "Item stat penalties like -3 DEX now count, and abilities with flat damage are no longer left out of the total.",
      "DPS answers no longer assume a Berserk buff the set cannot actually provide.",
    ],
  },
  {
    version: "2026.09.17-12",
    date: "Sep 17, 2026",
    items: [
      "Ask for a breakdown after a DPS answer and RealmPal now shows the full math instead of losing track of its own numbers.",
      "What-if questions like \"what if he swapped to a Doom Bow?\" now stay on DPS and rescale from the set you were just looking at.",
      "Everyday words no longer get mistaken for stat names, so a plain follow-up question stops pulling in an unrelated build.",
    ],
  },
  {
    version: "2026.09.17-11",
    date: "Sep 17, 2026",
    items: [
      "Fixed a bug that could leave the whole page unresponsive after an update. RealmPal now refreshes itself instead.",
      "Ability damage in DPS answers now comes from the item's real damage line, so the scaling stat is right.",
      "A player's DPS no longer comes back blank when one of their equipped items is new to us.",
      "When part of a set's damage cannot be measured, RealmPal says so instead of showing it as the full total.",
    ],
  },
  {
    version: "2026.09.17-10",
    date: "Sep 17, 2026",
    items: [
      "Asking for a player's class DPS now uses that character's RealmEye gear and stats, not only the leaderboard.",
      "The account-menu notifications panel opens as an overlay instead of freezing chat.",
    ],
  },
  {
    version: "2026.09.17-9",
    date: "Sep 17, 2026",
    items: [
      "Potential DPS now reads every equipped piece's wiki page for buffs and procs, then counts the ones that stay up on the dummy.",
    ],
  },
  {
    version: "2026.09.17-8",
    date: "Sep 17, 2026",
    items: [
      "Asking for max stats or potential DPS now answers with RealmShark numbers, including the enchants already on those sets, instead of only listing gear.",
      "If you swap a piece, the reply scales that board number instead of inventing a new DPS.",
      "Ability damage now follows wiki scaling and ability enchants, so armor procs like Vesture's Attack boost count when you swap.",
      "Potential DPS now tracks RealmShark more closely, including wiki Vulnerable and weapon enchants.",
    ],
  },
  {
    version: "2026.09.17-7",
    date: "Sep 17, 2026",
    items: [
      "Asking for a shiny item now uses the untiered version. Set pieces cannot be shiny.",
      "Short names understand sister weapon types, like staff and spellblade.",
      "The message box greys in the rest of the current word from the wiki store, even mid-sentence. Tab fills it in.",
      "Uncommon, Rare, and Legendary items now show their slot diamonds, same as Divine.",
    ],
  },
  {
    version: "2026.09.17-6",
    date: "Sep 17, 2026",
    items: [
      "Short names like fungal star now match the dungeon item, including Crystal Cavern.",
      "The message box suggests warmed item and dungeon names. Tab fills the first one in.",
      "Limited Edition clones are replaced with the original item in answers.",
    ],
  },
  {
    version: "2026.09.17-5",
    date: "Sep 17, 2026",
    items: [
      "Asking what a dungeon or boss drops now uses that source's wiki loot table, including Nox and Twilight Archmage.",
    ],
  },
  {
    version: "2026.09.17-4",
    date: "Sep 17, 2026",
    items: [
      "Asking whether a dungeon or the Keyper drops shinies now uses the wiki loot table instead of guessing item names.",
    ],
  },
  {
    version: "2026.09.17-3",
    date: "Sep 17, 2026",
    items: [
      "Your remaining free in-depth replies now live in the account menu, under Register. Tap it to upgrade.",
      "On a phone, leftover suggestions above the input drop the skin preview so three fit.",
      "Upgrade preview videos show a play button if a phone blocks autoplay.",
    ],
  },
  {
    version: "2026.09.17-2",
    date: "Sep 17, 2026",
    items: [
      "Asking how to farm Ogmur or Jailer's Scythe now shows a short sprite guide with arrows for what to bring and what to skip.",
      "The top-right quota line is now a Feedback button so you can tell us what to keep and what to fix.",
    ],
  },
  {
    version: "2026.09.17",
    date: "Sep 17, 2026",
    items: [
      "You can drop or paste RotMG screenshots into the message box, and they show up as pictures before you send.",
      "Click a screenshot in chat to zoom it, the same way item sprites zoom.",
      "Veteran biomes like Floral Escape, Carboniferous, and Sanguine Forest now answer potion-farm questions.",
      "Item cards and drop questions now use the drop locations from each RealmEye wiki page.",
    ],
  },
  {
    version: "2026.09.16-13",
    date: "Sep 16, 2026",
    items: [
      "Upgrade preview videos now play on phones and other devices that were showing a blank player.",
    ],
  },
  {
    version: "2026.09.16-12",
    date: "Sep 16, 2026",
    items: [
      "Best bow, sword, armor, and ring lists now follow Umi and RealmShark, not the early-tier wiki table.",
      "Asking the same ability question again is instant and does not use another in-depth reply.",
      "Early, mid, and endgame item questions now get a class progression with dungeon routes and item pictures.",
    ],
  },
  {
    version: "2026.09.16-11",
    date: "Sep 16, 2026",
    items: [
      "An earlier build answer no longer comes back when you ask something else. If you are out of in-depth replies, that new question opens the upgrade popup.",
    ],
  },
  {
    version: "2026.09.16-10",
    date: "Sep 16, 2026",
    items: [
      "Register from the guest menu now opens the same create-account form as the upgrade preview.",
      "Data sources and the DECA disclaimer now live under About in the account menu.",
    ],
  },
  {
    version: "2026.09.16-9",
    date: "Sep 16, 2026",
    items: [
      "The tab icon is the RealmPal sword, and switches to your pet once you have one set.",
      "The upgrade preview now plays short demo videos on the first two slides.",
      "Build answers now name the real best gear, including Vesture, Tools of the Tarnished, and The Forgotten Crown.",
      "Lookups and outfit previews stay free. The upgrade popup comes back when you are out of in-depth answers for the day.",
    ],
  },
  {
    version: "2026.09.15",
    date: "Sep 15, 2026",
    timestamp: "2026-09-15T10:49:50-07:00",
    items: [
      "On phones, sidebar suggestion prompts start hidden, and that hide or show choice is remembered next time.",
      "The menu now has a New chat button above your chat list.",
      "The in-game name field now tells you to enter your IGN to find your pet.",
      "Finding your pet by IGN is much faster, with a clear message if your pet yard is hidden.",
      "Looking up the same player twice now keeps the character card.",
      "Listing a shiny weapon, ability, armor, and ring now shows the set preview.",
      "Item names still work with a small typo, and words like rare no longer break the lookup.",
    ],
  },
  {
    version: "2026.09.14-2",
    date: "Sep 14, 2026",
    timestamp: "2026-09-14T23:15:37-07:00",
    items: [
      "Phones now show the chat first, with a full-screen menu behind a button in the top left.",
      "The message box stays on screen above the Safari toolbar, so you no longer have to scroll to type.",
    ],
  },
  {
    version: "2026.09.14",
    date: "Sep 14, 2026",
    timestamp: "2026-09-14T22:37:35-07:00",
    items: [
      "Chat answers are grounded in real wiki data again, across every kind of question.",
      "Dungeon guides and the skin/outfit visualizer are back to full strength after a rough patch.",
      "Skin visualizer follow-ups, like correcting a name or asking for just the shiny or divine version, work more reliably.",
      "Full outfit and set requests load correctly instead of spinning forever.",
      "Enchanting advice no longer suggests rare enchants that only fit one specific item.",
      "Asking about an item's enchant right after a build question now gets a real answer instead of repeating the build.",
      "Follow-up questions about a completely different item no longer get answered with your last unrelated build.",
      "Signed-in chats now stay saved to your account, even if you're in a private/incognito window that later closes.",
      "Your in-game name and pet companion now show up in the sidebar automatically after signing in, on any device.",
      "Your free daily messages now reset at the same time each day for everyone, instead of depending on when you first messaged.",
      "Tapping the sides of the upgrade screen now flips between slides, like a story.",
      "Asking about an item in the same sentence as an unrelated follow-up question now correctly shows that item, instead of a broken result.",
      "Asking for a shiny/divine build by class and stat (like \"attack huntress\" or \"a set for dex huntress\") no longer errors out trying to look it up as a single item.",
      "Asking to see a full shiny/divine build by class and stat now shows the actual recommended weapon, ability, armor, and ring as a loadout, instead of a wall of text.",
    ],
  },
  {
    version: "2026.09.13",
    date: "Sep 13, 2026",
    timestamp: "2026-09-13T16:49:30-07:00",
    items: [
      "Pro gets more chat included every month, plus an optional pay-as-you-go option so you're never stuck waiting.",
      "Checkout now offers Link, so returning Stripe customers can pay without retyping their card.",
      "Ask for enchants on an item and RealmPal now figures out the build that fits it (like Attack for a +20 Attack item) instead of listing every option.",
      "Drops, best gear, and build guides now answer instantly.",
      "You can now see exactly when your free daily messages reset.",
      "Billing and usage now live in the account menu.",
      "Daily quests now live in chat. Finish today's set for an extra message.",
      "Each daily quest now shows today's dungeon portal, an eyeball for player lookup, or a shiny item, all the same size.",
      "Quest icons stay visible when a dungeon name is long.",
      "Sign in and registration no longer spin forever if the server is slow. You'll see a clear message and can just try again.",
      "Looking up a player, item, or dungeon now shows a clear message instead of spinning forever if it's taking too long.",
      "Dungeon portals show up again after you refresh daily quests.",
      "The Shatters quest now shows the real dungeon portal, not the ice portal inside it.",
      "Hardmode Shatters again uses the purple Source dome as its portal.",
      "The shiny star only shows when that item actually has a shiny version.",
      "The top bar is now messages left, What’s new, Quests, Sign in, then your profile.",
      "The Quests button in the top bar shows your daily progress again.",
      "The top-right buttons now sit on their own tab so they don't cover your chat.",
      "The free-message popup now tells you exactly how many free messages you have left, instead of always showing a countdown.",
      "Creating an account now loads your pet into the sidebar right away.",
      "Starting a chat from a daily quest or a suggested question now shows up in your chat list like any other chat.",
    ],
  },
  {
    version: "prelaunch",
    date: "Development phases before going live",
    phase: true,
    items: [
      "Fixed a rare case where the daily quest bonus message could disappear or reset too early.",
      "Pro members can now manage or cancel their subscription right from the billing menu, no more emailing support.",
      "The Quests progress bar sits under the Quests label.",
      "Hovering a shiny quest item now shows its name instead of clipping it.",
      "Dungeon guides no longer stall or drop item cards after a long drop list.",
      "The quests refresh button now picks a new dungeon and a new shiny item.",
      "Refreshing quests now swaps the shiny item art instead of leaving the last one stuck.",
      "The shiny quest now uses the same divine glow and diamonds as a visualized set.",
      "Dungeon quest names no longer include leftover wiki text.",
      "Dungeon guides now show the real dungeon portal, not the ice portal inside The Shatters.",
      "The daily quests window opens again.",
      "Finished daily quests stay clickable, with a pointer cursor on hover.",
      "Click any item sprite to zoom it full size. Tap the backdrop to close.",
      "The message reset countdown is now easier to spot in mustard yellow.",
      "Item zoom now keeps divine glow, shiny stars, and stats, with a link back to RealmEye.",
      "Dungeon guides now show the right difficulty graves and less repeated wiki text.",
      "Layout maps in dungeon guides are sized down so they do not blow up the chat.",
      "Drop icons in dungeon guides are a bit larger.",
      "The top bar buttons have a little more breathing room.",
      "Billing now shows a usage progress bar with a percentage, above your plan.",
      "Pro users can set a pay-as-you-go spending limit ($20, $50, $100, or custom) from Billing.",
      "When your included replies run out, the paywall and Billing both let you manage your spending limit.",
      "Skin preview questions like 'what does X look like with Y cloth' now resolve the skin name correctly.",
      "Skin previews render instantly without calling Claude, and show a clear message if RealmEye cannot composite the outfit.",
      "Clickable buttons and links now show the pointer cursor consistently.",
      "The sidebar account row now shows your IGN with your email underneath.",
      "Your sidebar pet now saves with your account and shows up everywhere you sign in.",
      "Skin preview follow-ups like 'what does it look like with small black dye' keep the same skin from earlier in the chat.",
      "The skin preview card applies one cloth or dye to both clothing and accessory.",
      "Saying switch in a skin preview now swaps the clothing and accessory instantly.",
      "Swapping a cloth preview turns Large cloth into Small cloth on the other slot.",
      "Signed-in accounts no longer use a chat message on instant answers like drops and skin previews.",
      "Dungeon guides still use the RealmEye writeup, without leftover wiki banners and duplicate pages.",
      "Dungeon cards, item sprites, and skin previews stay when you reopen a chat.",
      "The Quests tab now shows your daily progress as a small percentage beside the bar.",
      "Build guides use the stronger model on the first ask, then replay instantly from your saved answer.",
      "Build prompts now understand common class nicknames like pally, trix, sorc, hunt, and wiz.",
      "Your chats and daily quest progress stay with your account when you sign out and back in.",
      "Clicking today's shiny quest now shows that item right away.",
      "Your top pet is now the one with the highest RealmEye ability levels, not the first pet in the yard.",
      "Click a character, item, or skin card to see a larger copy of the whole card in the center of the screen. Gear icons and links on the card still work as their own clicks.",
    ],
  },
];

/** Newest version, derived automatically. Don't hand-edit this. */
export const LATEST_VERSION = CHANGELOG[0]?.version ?? "";

const STORAGE_KEY = "realm_pal_changelog_seen";

/** True if the visitor hasn't seen the latest changelog entry yet. */
export function hasUnseenChangelog(): boolean {
  if (typeof window === "undefined" || !LATEST_VERSION) return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== LATEST_VERSION;
  } catch {
    return false;
  }
}

/** Marks the latest changelog entry as seen, so the popup won't nag again. */
export function markChangelogSeen(): void {
  if (typeof window === "undefined" || !LATEST_VERSION) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, LATEST_VERSION);
  } catch {
    // Private mode / storage disabled. Not worth failing over.
  }
}
