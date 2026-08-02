"""Domain layer: provider-agnostic core objects of the Intelligence Core.

Unlike app.models (ORM rows tied to a table), objects here are the conceptual
vocabulary the intelligence layers reason in - starting with the canonical
Finding (Phase 1). Later phases add Entity (Phase 2) and the cross-provider
Situation (Phase 3) here.
"""
