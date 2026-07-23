from app.core.config import get_settings
from app.factory import create_app

app = create_app(get_settings())
