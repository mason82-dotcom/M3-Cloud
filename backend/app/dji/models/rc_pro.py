from __future__ import annotations


RC_PRO_ENTERPRISE_PRODUCT_TYPE = 144
RC_PRO_ENTERPRISE_SUB_TYPE = 0
RC_PRO_ENTERPRISE_MODEL = "DJI_RC_PRO_ENTERPRISE"

# The current Pilot-to-Cloud RC Pro property table exposes read-only state.
RC_PRO_WRITABLE_PROPERTIES: frozenset[str] = frozenset()


def is_rc_pro_enterprise_identity(product_type: object, sub_type: object) -> bool:
    return (
        isinstance(product_type, int)
        and not isinstance(product_type, bool)
        and product_type == RC_PRO_ENTERPRISE_PRODUCT_TYPE
        and isinstance(sub_type, int)
        and not isinstance(sub_type, bool)
        and sub_type == RC_PRO_ENTERPRISE_SUB_TYPE
    )
