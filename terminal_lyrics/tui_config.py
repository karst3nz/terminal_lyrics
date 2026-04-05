"""Interactive TUI configuration for terminal_lyrics."""

from __future__ import annotations

import sys
from pathlib import Path

from terminal_lyrics.config import load_config, save_visual_config, VisualConfig
from terminal_lyrics.render.themes import ThemeManager


def clear_screen():
    """Clear the terminal screen."""
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()


def print_header():
    """Print the configuration header."""
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║           TERMINAL_LYRICS - Визуальная конфигурация                 ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print()


def print_menu(title: str, options: list[tuple[str, str]], current: str = ""):
    """Print a menu with options."""
    print(f"\n{title}:")
    print("-" * 70)
    for i, (key, desc) in enumerate(options, 1):
        marker = "►" if key == current else " "
        print(f"{marker} {i}. {desc}")
    print()


def get_choice(prompt: str, max_choice: int) -> int:
    """Get user choice."""
    while True:
        try:
            choice = input(f"{prompt} (1-{max_choice}): ").strip()
            if not choice:
                return 0
            num = int(choice)
            if 1 <= num <= max_choice:
                return num
            print(f"Пожалуйста, введите число от 1 до {max_choice}")
        except ValueError:
            print("Пожалуйста, введите число")
        except KeyboardInterrupt:
            print("\n\nОтменено")
            sys.exit(0)


def get_yes_no(prompt: str, default: bool = True) -> bool:
    """Get yes/no answer."""
    default_str = "Y/n" if default else "y/N"
    while True:
        try:
            answer = input(f"{prompt} ({default_str}): ").strip().lower()
            if not answer:
                return default
            if answer in ("y", "yes", "д", "да"):
                return True
            if answer in ("n", "no", "н", "нет"):
                return False
            print("Пожалуйста, введите y/yes или n/no")
        except KeyboardInterrupt:
            print("\n\nОтменено")
            sys.exit(0)


def configure_theme(cfg: VisualConfig) -> str:
    """Configure theme."""
    clear_screen()
    print_header()

    theme_manager = ThemeManager()
    themes = theme_manager.list_themes()

    theme_options = [(theme, theme) for theme in themes]
    print_menu("Выберите цветовую тему", theme_options, cfg.theme)

    print("Доступные темы:")
    for i, theme in enumerate(themes, 1):
        marker = "►" if theme == cfg.theme else " "
        print(f"{marker} {i}. {theme}")

    print("\n0. Назад")

    choice = get_choice("Выберите тему", len(themes))
    if choice == 0:
        return cfg.theme

    return themes[choice - 1]


def configure_border(cfg: VisualConfig) -> str:
    """Configure border style."""
    clear_screen()
    print_header()

    borders = [
        ("rounded", "Rounded (╭─╮) - скругленные углы"),
        ("double", "Double (╔═╗) - двойные линии"),
        ("single", "Single (┌─┐) - одинарные линии"),
        ("heavy", "Heavy (┏━┓) - жирные линии"),
        ("ascii", "ASCII (+--+) - совместимость"),
    ]

    print_menu("Выберите стиль рамки", borders, cfg.border_style)

    print("\nПримеры:")
    print("  1. ╭─────╮  Rounded")
    print("  2. ╔═════╗  Double")
    print("  3. ┌─────┐  Single")
    print("  4. ┏━━━━━┓  Heavy")
    print("  5. +-----+  ASCII")
    print("\n0. Назад")

    choice = get_choice("Выберите стиль", len(borders))
    if choice == 0:
        return cfg.border_style

    return borders[choice - 1][0]


def configure_visualizer(cfg: VisualConfig) -> tuple[bool, str]:
    """Configure visualizer."""
    clear_screen()
    print_header()

    print("Музыкальный визуализатор")
    print("-" * 70)

    enabled = get_yes_no("Включить визуализатор?", cfg.show_visualizer)

    if not enabled:
        return False, cfg.visualizer_style


    return enabled, "equalizer"


def configure_layout(cfg: VisualConfig) -> tuple[bool, bool, bool]:
    """Configure layout options."""
    clear_screen()
    print_header()

    print("Настройки отображения")
    print("-" * 70)

    progress = get_yes_no("Показывать прогресс-бар?", cfg.show_progress_bar)
    center = get_yes_no("Центрировать текст?", cfg.center_text)
    animations = get_yes_no("Включить анимации?", cfg.enable_animations)

    return progress, center, animations


def preview_config(cfg: VisualConfig):
    """Preview current configuration."""
    clear_screen()
    print_header()

    print("Текущая конфигурация:")
    print("-" * 70)
    print(f"  Тема:              {cfg.theme}")
    print(f"  Стиль рамки:       {cfg.border_style}")
    print(f"  Прогресс-бар:      {'включен' if cfg.show_progress_bar else 'выключен'}")
    print(f"  Визуализатор:      {'включен' if cfg.show_visualizer else 'выключен'}")
    if cfg.show_visualizer:
        print(f"  Стиль визуализ.:   {cfg.visualizer_style}")
    print(f"  Центрировать:      {'да' if cfg.center_text else 'нет'}")
    print(f"  Анимации:          {'включены' if cfg.enable_animations else 'выключены'}")
    print("-" * 70)
    print()


def main_menu():
    """Main configuration menu."""
    cfg = load_config()

    # Convert to dict for easier manipulation
    visual_dict = {
        "theme": cfg.visual.theme,
        "border_style": cfg.visual.border_style,
        "show_progress_bar": cfg.visual.show_progress_bar,
        "show_metadata": cfg.visual.show_metadata,
        "show_visualizer": cfg.visual.show_visualizer,
        "visualizer_style": cfg.visual.visualizer_style,
        "visualizer_position": cfg.visual.visualizer_position,
        "center_text": cfg.visual.center_text,
        "enable_animations": cfg.visual.enable_animations,
        "enable_gradient": cfg.visual.enable_gradient,
        "enable_pulse": cfg.visual.enable_pulse,
    }

    while True:
        clear_screen()
        print_header()

        # Show current config
        print("Текущая конфигурация:")
        print("-" * 70)
        print(f"  Тема:         {visual_dict['theme']}")
        print(f"  Рамка:        {visual_dict['border_style']}")
        print(f"  Прогресс-бар: {'✓' if visual_dict['show_progress_bar'] else '✗'}")
        print(
            f"  Визуализатор: {'✓' if visual_dict['show_visualizer'] else '✗'} ({visual_dict['visualizer_style']})"
        )
        print(f"  Центрировать: {'✓' if visual_dict['center_text'] else '✗'}")
        print(f"  Анимации:     {'✓' if visual_dict['enable_animations'] else '✗'}")
        print("-" * 70)
        print()

        print("Меню настройки:")
        print("  1. Изменить тему")
        print("  2. Изменить стиль рамки")
        print("  3. Настроить визуализатор")
        print("  4. Настройки отображения")
        print("  5. Сохранить и выйти")
        print("  0. Выйти без сохранения")
        print()

        choice = get_choice("Выберите действие", 5)

        if choice == 0:
            print("\nВыход без сохранения...")
            return
        elif choice == 1:
            visual_dict["theme"] = configure_theme(VisualConfig(**visual_dict))
        elif choice == 2:
            visual_dict["border_style"] = configure_border(VisualConfig(**visual_dict))
        elif choice == 3:
            enabled, style = configure_visualizer(VisualConfig(**visual_dict))
            visual_dict["show_visualizer"] = enabled
            visual_dict["visualizer_style"] = style
        elif choice == 4:
            progress, center, animations = configure_layout(VisualConfig(**visual_dict))
            visual_dict["show_progress_bar"] = progress
            visual_dict["center_text"] = center
            visual_dict["enable_animations"] = animations
        elif choice == 5:
            # Save configuration
            new_visual = VisualConfig(**visual_dict)
            save_visual_config(new_visual)

            clear_screen()
            print_header()
            print("✓ Конфигурация сохранена!")
            print()
            preview_config(new_visual)
            print("\nЗапустите приложение:")
            print("  terminal-lyrics watch")
            print()
            return


def run():
    """Run the TUI configurator."""
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\nОтменено")
        sys.exit(0)


if __name__ == "__main__":
    run()
