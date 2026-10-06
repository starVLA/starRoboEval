"""Profile factory for the existing anonymous mailbox policy."""


def create_policy(*, config, identity, **parameters):
    from AgentPolicies.anonymous_code_agent.mailbox import MailboxPolicy

    parameters.setdefault("min_action_decisions_before_give_up", config["min_action_decisions_before_give_up"])
    return MailboxPolicy(**identity, max_response_bytes=config["max_response_bytes"], **parameters)
