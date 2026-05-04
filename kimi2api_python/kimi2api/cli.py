"""
Command-Line Interface for Kimi2API
Provides commands for managing the API proxy, API keys, and configuration.
"""

import sys
import argparse
from typing import Optional

from .config import config, save_config, reload_config, CONFIG_DIR
from .apikey_manager import api_key_manager
from .server import run_server


def cmd_config(args) -> int:
    """Show or update configuration"""
    if args.action == "show":
        print("=== Kimi2API Configuration ===")
        print(f"Config file: {config.__class__.__module__}")
        print(f"Host: {config.host}")
        print(f"Port: {config.port}")
        print(f"Kimi Token: {'***configured***' if config.kimi_token else 'NOT SET'}")
        print(f"API Key Auth: {'enabled' if config.enable_api_key else 'disabled'}")
        print(f"API Keys: {len(api_key_manager.list_keys())} keys")
        print(f"Log Level: {config.log_level}")
        print("\nModel Mappings:")
        for k, v in config.model_mapping.items():
            print(f"  {k} -> {v}")
        return 0

    elif args.action == "set-token":
        token = args.value
        if not token:
            print("Error: Token value is required")
            return 1
        config.kimi_token = token
        save_config(config)
        print("Kimi token updated successfully.")
        return 0

    elif args.action == "set-port":
        port = int(args.value)
        if port < 1 or port > 65535:
            print("Error: Port must be between 1 and 65535")
            return 1
        config.port = port
        save_config(config)
        print(f"Port updated to {port}.")
        return 0

    elif args.action == "set-host":
        config.host = args.value
        save_config(config)
        print(f"Host updated to {args.value}.")
        return 0

    elif args.action == "set-log-level":
        level = args.value.upper()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            print("Error: Log level must be DEBUG, INFO, WARNING, or ERROR")
            return 1
        config.log_level = level
        save_config(config)
        print(f"Log level updated to {level}.")
        return 0

    else:
        print(f"Unknown config action: {args.action}")
        return 1


def cmd_keys(args) -> int:
    """Manage API keys"""
    if args.action == "list":
        keys = api_key_manager.list_keys()
        if not keys:
            print("No API keys configured.")
            return 0
        print(f"{'Prefix':<20} {'Name':<20} {'Status':<12} {'Created'}")
        print("-" * 80)
        from datetime import datetime
        for k in keys:
            status = "enabled" if k.enabled else "revoked"
            created = datetime.fromtimestamp(k.created_at).strftime("%Y-%m-%d %H:%M")
            print(f"{k.prefix:<20} {k.name:<20} {status:<12} {created}")
        return 0

    elif args.action == "create":
        name = args.name or ""
        key = api_key_manager.create_key(name)
        print("=" * 60)
        print("NEW API KEY CREATED - SAVE IT NOW!")
        print("This key will NOT be shown again!")
        print("=" * 60)
        print(f"\n  {key}\n")
        print("=" * 60)
        print("Usage:")
        print(f'  curl -H "Authorization: Bearer {key}" \\')
        print(f'       -H "Content-Type: application/json" \\')
        print(f'       -d \'{{"model":"kimi-k2.5","messages":[{{"role":"user","content":"Hello"}}]}}\' \\')
        print(f'       http://{config.host}:{config.port}/v1/chat/completions')
        return 0

    elif args.action == "revoke":
        if api_key_manager.revoke_key(args.prefix_or_name):
            print(f"Key '{args.prefix_or_name}' revoked.")
        else:
            print(f"Key '{args.prefix_or_name}' not found.")
            return 1
        return 0

    elif args.action == "enable":
        if api_key_manager.enable_key(args.prefix_or_name):
            print(f"Key '{args.prefix_or_name}' enabled.")
        else:
            print(f"Key '{args.prefix_or_name}' not found.")
            return 1
        return 0

    elif args.action == "delete":
        if api_key_manager.delete_key(args.prefix_or_name):
            print(f"Key '{args.prefix_or_name}' deleted permanently.")
        else:
            print(f"Key '{args.prefix_or_name}' not found.")
            return 1
        return 0

    else:
        print(f"Unknown keys action: {args.action}")
        return 1


def cmd_serve(args) -> int:
    """Start the API server"""
    host = args.host or config.host
    port = args.port or config.port

    print("=" * 50)
    print("  Kimi2API Server")
    print("=" * 50)
    print(f"  Listening on: http://{host}:{port}")
    print(f"  API Key Auth: {'ON' if config.enable_api_key and config.api_keys else 'OFF'}")
    print(f"  Kimi Token: {'Configured' if config.kimi_token else 'NOT SET!'}")
    print(f"  API Endpoint: http://{host}:{port}/v1/chat/completions")
    print(f"  Health Check: http://{host}:{port}/health")
    print("=" * 50)

    if not config.kimi_token:
        print("\nWARNING: Kimi token is not configured!")
        print("Run: kimi2api config set-token <your_token>")
        print("Get your token from: https://www.kimi.com (F12 -> Application -> Cookies/Local Storage)")
        print()

    run_server(host=host, port=port)
    return 0


def cmd_model(args) -> int:
    """Manage model mappings"""
    if args.action == "list":
        print("Model Mappings:")
        for openai_name, kimi_name in config.model_mapping.items():
            print(f"  {openai_name} -> {kimi_name}")
        return 0

    elif args.action == "add":
        if not args.openai_model or not args.kimi_model:
            print("Error: Both --openai and --kimi are required")
            return 1
        config.model_mapping[args.openai_model] = args.kimi_model
        save_config(config)
        print(f"Mapping added: {args.openai_model} -> {args.kimi_model}")
        return 0

    elif args.action == "remove":
        if args.openai_model in config.model_mapping:
            del config.model_mapping[args.openai_model]
            save_config(config)
            print(f"Mapping removed: {args.openai_model}")
        else:
            print(f"Mapping not found: {args.openai_model}")
            return 1
        return 0

    else:
        print(f"Unknown model action: {args.action}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser"""
    parser = argparse.ArgumentParser(
        prog="kimi2api",
        description="Kimi Web Chat to OpenAI-Compatible API Proxy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  kimi2api config set-token "eyJhbGciOi..."
  kimi2api keys create --name "my-app"
  kimi2api serve --port 8080
  kimi2api model add --openai gpt-4 --kimi kimi-k2.5
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # config command
    config_parser = subparsers.add_parser("config", help="Manage configuration")
    config_sub = config_parser.add_subparsers(dest="action", help="Config actions")
    
    config_show = config_sub.add_parser("show", help="Show current configuration")
    config_show.set_defaults(func=cmd_config)
    
    config_token = config_sub.add_parser("set-token", help="Set Kimi access token")
    config_token.add_argument("value", help="JWT or refresh token from Kimi website")
    config_token.set_defaults(func=cmd_config)
    
    config_port = config_sub.add_parser("set-port", help="Set server port")
    config_port.add_argument("value", type=int, help="Port number (1-65535)")
    config_port.set_defaults(func=cmd_config)
    
    config_host = config_sub.add_parser("set-host", help="Set server host")
    config_host.add_argument("value", help="Host address (e.g., 127.0.0.1)")
    config_host.set_defaults(func=cmd_config)
    
    config_log = config_sub.add_parser("set-log-level", help="Set log level")
    config_log.add_argument("value", help="Log level: DEBUG, INFO, WARNING, ERROR")
    config_log.set_defaults(func=cmd_config)

    # keys command
    keys_parser = subparsers.add_parser("keys", help="Manage API keys")
    keys_sub = keys_parser.add_subparsers(dest="action", help="Key management actions")
    
    keys_list = keys_sub.add_parser("list", help="List all API keys")
    keys_list.set_defaults(func=cmd_keys)
    
    keys_create = keys_sub.add_parser("create", help="Create a new API key")
    keys_create.add_argument("--name", "-n", help="Key name/label")
    keys_create.set_defaults(func=cmd_keys)
    
    keys_revoke = keys_sub.add_parser("revoke", help="Revoke (disable) an API key")
    keys_revoke.add_argument("prefix_or_name", help="Key prefix or name to revoke")
    keys_revoke.set_defaults(func=cmd_keys)
    
    keys_enable = keys_sub.add_parser("enable", help="Re-enable a revoked API key")
    keys_enable.add_argument("prefix_or_name", help="Key prefix or name to enable")
    keys_enable.set_defaults(func=cmd_keys)
    
    keys_delete = keys_sub.add_parser("delete", help="Permanently delete an API key")
    keys_delete.add_argument("prefix_or_name", help="Key prefix or name to delete")
    keys_delete.set_defaults(func=cmd_keys)

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start the API server")
    serve_parser.add_argument("--host", "-H", help="Host to bind to")
    serve_parser.add_argument("--port", "-p", type=int, help="Port to listen on")
    serve_parser.set_defaults(func=cmd_serve)

    # model command
    model_parser = subparsers.add_parser("model", help="Manage model mappings")
    model_sub = model_parser.add_subparsers(dest="action", help="Model mapping actions")
    
    model_list = model_sub.add_parser("list", help="List all model mappings")
    model_list.set_defaults(func=cmd_model)
    
    model_add = model_sub.add_parser("add", help="Add a model mapping")
    model_add.add_argument("--openai", dest="openai_model", required=True, help="OpenAI model name")
    model_add.add_argument("--kimi", dest="kimi_model", required=True, help="Kimi model name")
    model_add.set_defaults(func=cmd_model)
    
    model_remove = model_sub.add_parser("remove", help="Remove a model mapping")
    model_remove.add_argument("--openai", dest="openai_model", required=True, help="OpenAI model name to remove")
    model_remove.set_defaults(func=cmd_model)

    return parser


def main(args: Optional[list[str]] = None) -> int:
    """Main CLI entry point"""
    parser = build_parser()
    
    if args is None:
        args = sys.argv[1:]

    if not args:
        parser.print_help()
        return 0

    parsed = parser.parse_args(args)

    if hasattr(parsed, "func"):
        return parsed.func(parsed)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
