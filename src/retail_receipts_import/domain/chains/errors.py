"""Errors a chain plug-in raises while turning a model response into a receipt."""


class UnreadableReceipt(Exception):
    """The response does not fit the schema, or a printed value in it cannot be parsed.

    The message names the field and value, never a whole response: responses carry receipt data.
    """
