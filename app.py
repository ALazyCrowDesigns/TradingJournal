from journal.container import container
from journal.ui.main_window import run_gui


def main() -> None:
    """Main application entry point"""
    # Initialize dependency injection container
    container.init_resources()

    # Run GUI with container
    run_gui(container)


if __name__ == "__main__":
    main()
