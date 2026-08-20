# если скрипту не доверяешь:

## Starship

```bash
curl -sS https://starship.rs/install.sh | sh

echo 'eval "$(starship init bash)"' >> ~/.bashrc
source ~/.bashrc
```

## локальный алиас sshc с инъекцией промпта

```bash
nano ~/.bashrc


sshc() {
  ssh -t "$@" "bash --rcfile <(cat << 'EOF'
# Подгружаем системные настройки сервера, если они есть
[ -f /etc/bash.bashrc ] && . /etc/bash.bashrc
[ -f ~/.bashrc ] && . ~/.bashrc

# Принудительно задаем яркий цветной промпт
# root подсвечивается красным, обычный пользователь — зеленым
if [ \$(id -u) -eq 0 ]; then
    PS1='\[\e[1;31m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\w\[\e[0m\]\$ '
else
    PS1='\[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\w\[\e[0m\]\$ '
fi

# Включаем подсветку вывода команд
alias ls='ls --color=auto'
alias ll='ls -la --color=auto'
alias grep='grep --color=auto'
EOF
)"
}


source ~/.bashrc
```
