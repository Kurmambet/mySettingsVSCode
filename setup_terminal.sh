#!/usr/bin/env bash
set -euo pipefail

echo "===> [1/4] Проверка необходимых утилит..."
if ! command -v curl &>/dev/null; then
    echo "Утилита curl не найдена. Установка через apt..."
    sudo apt update && sudo apt install -y curl
fi

echo "===> [2/4] Установка Starship..."
if ! command -v starship &>/dev/null; then
    curl -sS https://starship.rs/install.sh | sh -s -- -y
else
    echo "Starship уже установлен. Пропускаем..."
fi

echo "===> [3/4] Настройка конфигурации Starship (~/.config/starship.toml)..."
mkdir -p ~/.config
cat > ~/.config/starship.toml << 'EOF'
# Отключение скрытия родительских директорий и показ полного пути
[directory]
truncate_to_repo = false
truncation_length = 0
EOF

echo "===> [4/4] Добавление Starship и sshc в ~/.bashrc..."
BASHRC_MARKER="# --- CUSTOM DEV SHELL SETUP (Starship & sshc) ---"

if ! grep -q "$BASHRC_MARKER" ~/.bashrc 2>/dev/null; then
    cat >> ~/.bashrc << 'EOF'

# --- CUSTOM DEV SHELL SETUP (Starship & sshc) ---
# Инициализация Starship
eval "$(starship init bash)"

# Быстрое подключение по SSH с пробросом цветного промпта без файлов на сервере
sshc() {
  ssh -t "$@" "bash --rcfile <(cat << 'SSHEOF'
[ -f /etc/bash.bashrc ] && . /etc/bash.bashrc
[ -f ~/.bashrc ] && . ~/.bashrc

if [ \$(id -u) -eq 0 ]; then
    PS1='\[\e[1;31m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\w\[\e[0m\]\$ '
else
    PS1='\[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\w\[\e[0m\]\$ '
fi

alias ls='ls --color=auto'
alias ll='ls -la --color=auto'
alias grep='grep --color=auto'
SSHEOF
)"
}
# --- END CUSTOM DEV SHELL SETUP ---
EOF
    echo "Записи успешно добавлены в ~/.bashrc."
else
    echo "Конфигурация уже присутствует в ~/.bashrc. Пропускаем..."
fi

echo ""
echo "=== Установка завершена успешно! ==="
echo "Чтобы применить изменения прямо сейчас, выполните:"
echo "source ~/.bashrc"
