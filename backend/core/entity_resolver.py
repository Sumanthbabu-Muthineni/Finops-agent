import re
from typing import Optional, Tuple, List, Dict, Any
from rapidfuzz import process, fuzz
from backend.engine.db import db

class EntityResolver:
    def __init__(self):
        self.refresh_cache()

    def refresh_cache(self):
        entities = db.get_distinct_entities()
        self.banks = entities.get("banks", [])
        self.bank_codes = entities.get("bank_codes", [])
        self.entities = entities.get("entities", [])
        self.programs = entities.get("programs", [])
        self.vendors = self.banks  # backward-compatibility alias
        self.accounts = []
        self.categories = []

        # Query exact bank_code to bank_name mapping from PostgreSQL
        try:
            b_df, _, _ = db.execute_query("SELECT bank_code, bank_name FROM bank;")
            self.code_to_name = dict(zip(b_df["bank_code"], b_df["bank_name"]))
            self.name_to_code = dict(zip(b_df["bank_name"], b_df["bank_code"]))
        except Exception:
            self.code_to_name = {}
            self.name_to_code = {}

        self.dynamic_aliases = self._build_dynamic_aliases(self.banks)

    def _build_dynamic_aliases(self, banks: List[str]) -> Dict[str, str]:
        """
        Dynamically extracts banking acronyms, IFSC codes, and common shorthand directly from database bank names.
        No hardcoded lists.
        Example:
          'HDFC BANK LIMITED' (code 'HDFC') -> 'hdfc', 'hdfc bank'
          'STATE BANK OF INDIA' (code 'SBIN') -> 'sbin', 'sbi', 'state bank'
          'ICICI BANK LIMITED' (code 'ICIC') -> 'icic', 'icici', 'icici bank'
          'AXIS BANK LIMITED' (code 'UTIB') -> 'utib', 'axis', 'axis bank'
          'KOTAK MAHINDRA BANK LIMITED' (code 'KKBK') -> 'kkbk', 'kotak', 'kotak bank'
        """
        aliases = {}
        for b in banks:
            b_lower = b.lower()
            aliases[b_lower] = b

            # Add bank code (e.g. 'SBIN', 'UTIB', 'HDFC', 'ICIC')
            if hasattr(self, "name_to_code") and b in self.name_to_code:
                code = self.name_to_code[b].lower()
                aliases[code] = b

            words = [w for w in b.split() if w.lower() not in ["limited", "ltd", "bank", "small", "finance"]]
            # 1. Shorthand first word (e.g. "Kotak", "Axis", "Canara", "Union")
            if words:
                first_word = words[0].lower()
                if len(first_word) >= 3:
                    aliases[first_word] = b
                    aliases[f"{first_word} bank"] = b

            # 2. Dynamic Acronym (e.g. "SBI" for "STATE BANK OF INDIA", "AUBL" for "AU SMALL FINANCE BANK")
            clean_words = [w for w in b.split() if w.lower() not in ["limited", "ltd", "of", "&", "and"]]
            if len(clean_words) > 1:
                initials = "".join(w[0] for w in clean_words).lower()
                if len(initials) >= 2:
                    aliases[initials] = b
                    aliases[f"{initials} bank"] = b

        return aliases

    def get_aliases_for_vendor(self, vendor_name: str) -> List[str]:
        """Returns all dynamically generated aliases/shorthand for a given bank or vendor name."""
        return [alias for alias, canonical in self.dynamic_aliases.items() if canonical == vendor_name]

    def resolve_with_session(
        self,
        query: str,
        session_confirmed_entities: Optional[Dict[str, str]] = None,
        active_context_vendor: Optional[str] = None
    ) -> Tuple[Optional[str], float, bool, List[str], Optional[str]]:
        """
        Multi-turn aware entity resolution.
        Returns: (resolved_vendor, score, requires_confirmation, suggestions, matched_alias)
        """
        clean_q = query.lower()
        confirmed_map = session_confirmed_entities or {}

        # 0. Check Global All-Entity Queries (e.g. "for all entities", "all vendors", "select all")
        # Only apply if NO specific bank or dynamic alias is in the query
        has_specific_bank = any(
            re.search(r"\b" + re.escape(alias) + r"\b", clean_q)
            for alias in self.dynamic_aliases
        ) or any(
            re.search(r"\b" + re.escape(v.lower()) + r"\b", clean_q)
            for v in self.vendors
        )

        if not has_specific_bank:
            global_patterns = [
                r"\b(all entities|all vendors|all companies|all accounts|every vendor|across all|select all|for all entities|for all vendors|for all companies|for all|all of them|everyone)\b"
            ]
            for p in global_patterns:
                if re.search(p, clean_q):
                    return None, 1.0, False, [], None

        # 1. Check Session Memory: Did the user already confirm or discuss this acronym/alias in this session?
        for term, canonical in confirmed_map.items():
            if re.search(r"\b" + re.escape(term.lower()) + r"\b", clean_q):
                return canonical, 1.0, False, [], term

        # 2. Check Contextual Pronouns & Follow-ups ("who paid them", "what about them", "they", "their payouts")
        pronoun_patterns = [
            r"\b(who paid (them|to them|that vendor)|what about (them|their payouts|that vendor))\b",
            r"\b(they|them|their|that vendor|this vendor|the vendor)\b"
        ]
        for p in pronoun_patterns:
            if re.search(p, clean_q):
                if active_context_vendor:
                    return active_context_vendor, 1.0, False, [], None

        # 3. Check for exact full canonical vendor name in text (No confirmation needed)
        for v in self.vendors:
            if re.search(r"\b" + re.escape(v.lower()) + r"\b", clean_q):
                return v, 1.0, False, [], None

        # 4. Check for dynamically generated acronyms/aliases
        for alias, canonical in self.dynamic_aliases.items():
            # Match aliases strictly on word boundaries
            if re.search(r"\b" + re.escape(alias) + r"\b", clean_q):
                # If this canonical vendor is already the active context in this session, don't ask again!
                if active_context_vendor == canonical:
                    return canonical, 1.0, False, [], alias

                # If it's a short acronym/shorthand encountered for the FIRST time, ask for confirmation
                is_short_alias = (alias != canonical.lower())
                if is_short_alias:
                    return canonical, 0.65, True, [canonical], alias
                else:
                    return canonical, 1.0, False, [], alias

        # 5. Fuzzy string fallback via RapidFuzz
        words = [w.strip("?,.!'\"") for w in query.split() if len(w) > 2]
        for w in words:
            matched = process.extractOne(w, self.vendors, scorer=fuzz.token_sort_ratio)
            if matched and matched[1] >= 75.0:
                return matched[0], round(matched[1] / 100.0, 2), False, [], None

        # 6. Check if query was explicitly targeted at a named vendor that failed to match
        # E.g., "for vendor Foobar", "payouts for Acme", "paid to BarInc"
        is_vendor_targeted = False
        target_match = re.search(r"\b(vendor|payout to|paid to|expenses for)\s+([a-zA-Z0-9_-]+)", clean_q)
        if target_match:
            target_word = target_match.group(2).lower()
            if target_word not in ["all", "each", "every", "name", "id", "list", "spend", "spending", "payout", "payouts", "payment", "payments", "transaction", "transactions", "expense", "expenses", "status", "pending", "completed", "wire", "ach", "credit", "bills", "invoices", "records"]:
                is_vendor_targeted = True

        if is_vendor_targeted:
            top_suggestions = [m[0] for m in process.extract(query, self.vendors, scorer=fuzz.token_sort_ratio, limit=4)]
            return None, 0.0, False, top_suggestions, None
        else:
            # General query without a specific vendor constraint (e.g. "payments in pending for all entities", "unreconciled txns")
            return None, 1.0, False, [], None

    def resolve_vendor(self, query: str, threshold: float = 75.0) -> Tuple[Optional[str], float, List[str]]:
        """Direct vendor/bank resolver with alias checking and RapidFuzz matching."""
        q_clean = query.strip().lower()
        if q_clean in self.dynamic_aliases:
            return self.dynamic_aliases[q_clean], 1.0, []
        matched = process.extractOne(query, self.vendors, scorer=fuzz.token_set_ratio)
        if matched and matched[1] >= threshold:
            return matched[0], round(matched[1] / 100.0, 2), []
        top_suggestions = [m[0] for m in process.extract(query, self.vendors, scorer=fuzz.token_set_ratio, limit=3)]
        return None, 0.0, top_suggestions

    def extract_known_entities(self, text: str) -> Dict[str, Any]:
        """Scans full user text and identifies any explicitly mentioned known banks, bank codes, or programs."""
        clean_text = text.lower()
        found_banks = [b for b in self.banks if b.lower() in clean_text]
        found_codes = [c for c in self.bank_codes if re.search(r"\b" + re.escape(c.lower()) + r"\b", clean_text)]
        found_programs = [p for p in self.programs if re.search(r"\b(program\s+" + re.escape(str(p)) + r"|" + re.escape(str(p)) + r")\b", clean_text)]

        return {
            "found_banks": found_banks,
            "found_bank_codes": found_codes,
            "found_programs": found_programs,
            "found_vendors": found_banks,
            "found_accounts": found_banks,
            "found_categories": []
        }

entity_resolver = EntityResolver()
