import re
import json
from typing import Tuple, Literal, Optional
from backend.core.entity_resolver import entity_resolver

IntentType = Literal["GREETING", "FINANCIAL", "OUT_OF_SCOPE"]

GREETING_REGEXES = [
    r"^(hi|hello|hey|greetings|howdy)[\s\.,!\?]*$",
    r"^(hi|hello|hey) there[\s\.,!\?]*$",
    r"^(hi|hello|hey)[\s,]+(who are you|what can you do|what do you do|help|can you help me).*",
    r"^how are you.*",
    r"^how('s| is) it going.*",
    r"^what('s| is) up.*",
    r"^(good morning|good afternoon|good evening|good day)[\s\.,!\?]*$",
    r"^(who are you|what are you|what do you do|what can you do)[\s\.,!\?]*$",
    r"^(help|can you help me|how does this work)[\s\.,!\?]*$",
    r"^(thank you|thanks|thank you so much)[\s\.,!\?]*$",
    r"^(bye|goodbye|see you|see ya)[\s\.,!\?]*$"
]

FINANCIAL_KEYWORDS = {
    "spend", "spent", "spending", "payout", "payouts", "cost", "costs", "costing",
    "transaction", "transactions", "reconcile", "reconciled", "reconciliation", "unreconciled",
    "vendor", "vendors", "invoice", "invoices", "invoicing", "account", "accounts",
    "bank", "banks", "banking", "balance", "balances", "available", "credit", "credits",
    "debit", "debits", "credited", "debited", "utr", "reference", "ref", "program", "programs",
    "deposit", "deposits", "withdrawal", "withdrawals", "transfer", "transfers", "inflow", "outflow",
    "ledger", "payment", "payments", "paid", "wire", "ach", "credit card", "disbursement",
    "disbursed", "expense", "expenses", "bill", "bills", "billing", "budget",
    "currency", "amount", "total", "average", "avg", "sum", "records", "highest",
    "lowest", "drill down", "breakdown", "all", "entities", "entity", "select",
    "everything", "overall", "everyone", "across", "both", "neither"
}

class IntentClassifier:
    def classify(self, query: str, llm_client=None) -> Tuple[IntentType, Optional[str]]:
        """
        Classifies user query into GREETING, FINANCIAL, or OUT_OF_SCOPE.
        Returns (intent_type, standard_narrative_or_None)
        """
        clean_q = query.strip().lower()

        # 1. Check for pure greetings and chit-chat
        for pattern in GREETING_REGEXES:
            if re.search(pattern, clean_q):
                # Ensure no financial keyword was also attached (e.g. "hi, how much did we spend...")
                tokens = set(re.findall(r"\b\w+\b", clean_q))
                if not tokens.intersection(FINANCIAL_KEYWORDS):
                    return "GREETING", self._get_greeting_response(clean_q)

        # 2. Check for explicit financial indicators (keywords, dynamic aliases, known vendors/accounts/categories)
        tokens = set(re.findall(r"\b\w+\b", clean_q))
        if tokens.intersection(FINANCIAL_KEYWORDS):
            return "FINANCIAL", None

        # Check conversational responses or selection terms (e.g. "select all", "for all", "neither")
        if re.search(r"\b(all|select all|for all|all entities|all vendors|both|neither|everything|everyone)\b", clean_q):
            return "FINANCIAL", None

        # Check known entities (vendors, chart of accounts, categories)
        known = entity_resolver.extract_known_entities(query)
        if known.get("found_vendors") or known.get("found_accounts") or known.get("found_categories"):
            return "FINANCIAL", None

        # Check dynamic aliases (e.g. AWS, GCP, etc.) derived from PostgreSQL
        for alias in entity_resolver.dynamic_aliases:
            if re.search(r"\b" + re.escape(alias) + r"\b", clean_q):
                return "FINANCIAL", None

        # Check multi-word vendor names or fuzzy matches
        for v in entity_resolver.vendors:
            if v.lower() in clean_q:
                return "FINANCIAL", None

        for a in entity_resolver.accounts:
            if a.lower() in clean_q:
                return "FINANCIAL", None

        # 3. Explicit out-of-scope questions (general trivia, jokes, weather, poems)
        out_of_scope_patterns = [
            r"^(what is the capital|who is the president|tell me a joke|write a poem|sing a song|recipe for|what's the weather|how is the weather)\b",
            r"\b(joke|weather|poem|song|recipe|capital of|movie|sports|game|president|news)\b"
        ]
        for pattern in out_of_scope_patterns:
            if re.search(pattern, clean_q):
                return "OUT_OF_SCOPE", self._get_out_of_scope_response(query)

        # 4. Optional: LLM fallback for ambiguous queries if provided
        if llm_client:
            try:
                prompt = (
                    f"Classify the following user message into either 'FINANCIAL' (questions about company finances, spend, vendors, transactions, payments) "
                    f"or 'OUT_OF_SCOPE' (unrelated general knowledge like weather, trivia, poems, recipes).\n"
                    f"User message: '{query}'\n"
                    f"Output JSON only: {{\"intent\": \"FINANCIAL\" | \"OUT_OF_SCOPE\"}}"
                )
                raw = llm_client.complete(prompt, system="You are an intent classifier. Output JSON only.")
                if "OUT_OF_SCOPE" in raw.upper():
                    return "OUT_OF_SCOPE", self._get_out_of_scope_response(query)
                elif "FINANCIAL" in raw.upper():
                    return "FINANCIAL", None
            except Exception:
                pass

        # In a financial assistant, default ambiguous domain-adjacent queries to FINANCIAL
        return "FINANCIAL", None

    def _get_dynamic_examples(self) -> Tuple[str, str, str]:
        v1 = entity_resolver.banks[0] if getattr(entity_resolver, "banks", None) else "HDFC BANK LIMITED"
        v2 = entity_resolver.banks[1] if len(getattr(entity_resolver, "banks", [])) > 1 else v1
        cat = "transactions"
        return v1, v2, cat

    def _get_greeting_response(self, clean_q: str) -> str:
        v1, v2, cat = self._get_dynamic_examples()
        if "how are you" in clean_q:
            return (
                "I'm doing well, thank you! 😊\n\n"
                "I am your **FinOps Banking Assistant**, built to help you instantly analyze your company's banking accounts, "
                "available balances, credits/debits, and transactions with 100% grounded accuracy (zero LLM arithmetic).\n\n"
                "Here are some questions you can ask me:\n"
                f"• **What is our total available balance across all banks?**\n"
                f"• **How much was credited vs debited in June 2026?**\n"
                f"• **What is our balance at {v1}?**\n"
                f"• **Lookup transaction reference 1715499972**"
            )
        elif any(w in clean_q for w in ["thank", "thanks"]):
            return (
                "You're very welcome! Let me know if you need any other bank balance details, "
                "credit/debit breakdowns, or transaction reference lookups."
            )
        elif any(w in clean_q for w in ["who are you", "what are you", "what can you do", "help"]):
            return (
                "I am an enterprise **FinOps Banking Assistant** designed for financial operations and treasury teams.\n\n"
                "Here is what I can do:\n"
                "• **Bank Balances & Accounts**: View available balances across all corporate banking accounts and programs.\n"
                "• **Transaction Analytics**: Analyze debit vs credit volume, monthly totals, and program flows.\n"
                "• **Reference ID Search**: Instant exact search by reference ID with sensitive account number masking.\n"
                "• **IQR Anomaly Detection**: Automatically flag statistical outliers exceeding normal historical bounds.\n"
                "• **Audit Trail**: View exact SQL queries and execution times for every answer.\n\n"
                f"Try asking: *'What is our total available balance across all banks?'* or *'What is our balance at {v1}?'*"
            )
        else:
            return (
                "Hello! How can I assist you with your banking and financial data today?\n\n"
                "You can ask me about:\n"
                f"• **Available Balances**: *'What is our total available balance across all banks?'*\n"
                f"• **Bank Breakdown**: *'Show balance breakdown for {v1}'*\n"
                "• **Transaction Volumes**: *'How much was credited vs debited in June 2026?'*\n"
                "• **Reference Lookup**: *'Lookup transaction reference 1715499972'*."
            )

    def _get_out_of_scope_response(self, query: str) -> str:
        v1, v2, _ = self._get_dynamic_examples()
        return (
            "I am specifically designed to assist with **company financial & banking operations** "
            "(bank accounts, available balances, transaction tracking, credit/debit breakdowns, and reference searches).\n\n"
            "I cannot assist with general knowledge or unrelated topics. "
            "Please ask a question related to your financial datasets, for example:\n"
            "• **'What is our total available balance across all banks?'**\n"
            "• **'How much was credited vs debited in June 2026?'**\n"
            f"• **'What is our balance at {v1}?'**\n"
            "• **'Lookup transaction reference 1715499972'**"
        )

intent_classifier = IntentClassifier()
