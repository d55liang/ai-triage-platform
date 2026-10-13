from app.database import execute_sql


ALLOWED_COLUMNS = ["message", "status"]


def _row_to_ticket(row: list) -> dict:
    return {
        "ticket_id": row[0]["stringValue"],
        "user_id": row[1]["stringValue"],
        "message": row[2]["stringValue"],
        "status": row[3]["stringValue"],
        "created_at": row[4]["stringValue"],
    }


def save_ticket(ticket: dict) -> dict:
    sql = """
        INSERT INTO tickets (ticket_id, user_id, message, status)
        VALUES (CAST(:ticket_id AS UUID), :user_id, :message, :status)
        RETURNING ticket_id::text, user_id, message, status, created_at::text
    """
    parameters = [
        {"name": "ticket_id", "value": {"stringValue": ticket["ticket_id"]}},
        {"name": "user_id", "value": {"stringValue": ticket["user_id"]}},
        {"name": "message", "value": {"stringValue": ticket["message"]}},
        {"name": "status", "value": {"stringValue": ticket["status"]}},
    ]
    response = execute_sql(sql, parameters)
    return _row_to_ticket(response["records"][0])


def fetch_all_tickets() -> list[dict]:
    sql = """
        SELECT ticket_id::text, user_id, message, status, created_at::text
        FROM tickets
    """
    response = execute_sql(sql)
    return [_row_to_ticket(row) for row in response["records"]]


def fetch_ticket(ticket_id: str):
    sql = """
        SELECT ticket_id::text, user_id, message, status, created_at::text
        FROM tickets
        WHERE ticket_id = CAST(:ticket_id AS UUID)
    """
    parameters = [
        {"name": "ticket_id", "value": {"stringValue": ticket_id}},
    ]
    response = execute_sql(sql, parameters)
    records = response["records"]
    if not records:
        raise KeyError(ticket_id)
    return _row_to_ticket(records[0])


def remove_ticket(ticket_id: str):
    sql = """
        DELETE FROM tickets
        WHERE ticket_id = CAST(:ticket_id AS UUID)
        RETURNING ticket_id::text, user_id, message, status, created_at::text
    """
    parameters = [
        {"name": "ticket_id", "value": {"stringValue": ticket_id}},
    ]
    response = execute_sql(sql, parameters)
    records = response["records"]
    if not records:
        raise KeyError(ticket_id)
    ticket = _row_to_ticket(records[0])
    ticket["status"] = "DELETED"
    return ticket


def modify_ticket(ticket_id: str, params: dict):
    columns = [column for column in params if column in ALLOWED_COLUMNS]

    if not columns:
        return fetch_ticket(ticket_id)

    set_clause = ", ".join(f"{column} = :{column}" for column in columns)

    sql = f"""
        UPDATE tickets
        SET {set_clause}
        WHERE ticket_id = CAST(:ticket_id AS UUID)
        RETURNING ticket_id::text, user_id, message, status, created_at::text
    """
    parameters = [
        {"name": "ticket_id", "value": {"stringValue": ticket_id}},
    ]
    parameters.extend([{"name": f"{column}", "value": {"stringValue": params[column]}} for column in columns])

    response = execute_sql(sql, parameters)
    records = response["records"]
    if not records:
        raise KeyError(ticket_id)
    return _row_to_ticket(records[0])
