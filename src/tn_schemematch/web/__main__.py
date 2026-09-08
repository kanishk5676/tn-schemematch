"""python -m tn_schemematch.web"""

from .app import create_app

if __name__ == "__main__":
    create_app(debug=True).run(host="127.0.0.1", port=5000, debug=True)
