from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_session


# scope="function" commits before the response is sent; the default "request"
# scope would commit after, so a failed commit could follow a success response.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]
