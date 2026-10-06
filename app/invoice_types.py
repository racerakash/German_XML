from __future__ import annotations


# UN/EDIFACT 1001 document name codes commonly used by EN 16931, XRechnung,
# ZUGFeRD/Factur-X, and adjacent invoicing workflows. Unknown codes remain
# renderable and are shown explicitly instead of being rejected.
DOCUMENT_TYPE_TITLES: dict[str, str] = {
    "71": "PAYMENT REQUEST",
    "80": "DEBIT NOTE",
    "81": "CREDIT NOTE",
    "82": "METERED SERVICES INVOICE",
    "83": "CREDIT NOTE",
    "84": "DEBIT NOTE",
    "102": "TAX NOTIFICATION",
    "218": "FINAL PAYMENT REQUEST",
    "219": "PAYMENT REQUEST",
    "261": "SELF-BILLED CREDIT NOTE",
    "325": "PRO FORMA INVOICE",
    "326": "PARTIAL INVOICE",
    "331": "COMMERCIAL INVOICE WITH PACKING LIST",
    "380": "COMMERCIAL INVOICE",
    "381": "CREDIT NOTE",
    "382": "COMMISSION NOTE",
    "383": "DEBIT NOTE",
    "384": "CORRECTED INVOICE",
    "385": "CONSOLIDATED INVOICE",
    "386": "PREPAYMENT INVOICE",
    "387": "HIRE INVOICE",
    "388": "TAX INVOICE",
    "389": "SELF-BILLED INVOICE",
    "390": "DELCREDERE INVOICE",
    "393": "FACTORED INVOICE",
    "394": "LEASE INVOICE",
    "395": "CONSIGNMENT INVOICE",
    "396": "FACTORED CREDIT NOTE",
    "575": "INSURER'S INVOICE",
    "623": "FORWARDER'S INVOICE",
    "780": "FREIGHT INVOICE",
    "817": "CLAIM NOTIFICATION",
    "870": "CONSULAR INVOICE",
    "875": "PARTIAL CONSTRUCTION INVOICE",
    "876": "PARTIAL FINAL CONSTRUCTION INVOICE",
    "877": "FINAL CONSTRUCTION INVOICE",
}


ROOT_DEFAULT_TITLES: dict[str, str] = {
    "Invoice": "INVOICE",
    "CreditNote": "CREDIT NOTE",
    "DebitNote": "DEBIT NOTE",
    "SelfBilledInvoice": "SELF-BILLED INVOICE",
    "SelfBilledCreditNote": "SELF-BILLED CREDIT NOTE",
    "CrossIndustryInvoice": "INVOICE",
}


def invoice_title(document_type_code: str | None, root_name: str) -> str:
    if document_type_code:
        known = DOCUMENT_TYPE_TITLES.get(document_type_code.strip())
        if known:
            return known
        default = ROOT_DEFAULT_TITLES.get(root_name, "INVOICE")
        return f"{default} (TYPE {document_type_code.strip()})"
    return ROOT_DEFAULT_TITLES.get(root_name, "INVOICE")
