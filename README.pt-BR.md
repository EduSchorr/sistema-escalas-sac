> **Idioma:** [English](README.md) · Português (Brasil)

# Sistema de Escalas

### Motor de escala por regras · permissões · auditoria · execução local

Aplicação local para gerenciar equipes em rodízio, cobertura de finais de semana e regras operacionais de jornada.

## Recursos da edição pública

- Geração automática de escalas por várias semanas;
- validação de jornada 5x2;
- limite de seis dias consecutivos;
- rodízio N2 de sábado e domingo;
- balanceamento da cobertura da equipe geral;
- rotação de fim de semana completo de folga;
- ajustes manuais de Trabalho / Folga / Férias / Afastamento;
- visualização por setor;
- controle de acesso por perfil;
- senhas com PBKDF2 e sessões;
- auditoria;
- backups SQLite;
- exportação compatível com Excel/CSV.

## Motor de escala

O motor público foi separado do servidor e possui testes próprios. As regras representam um modelo operacional específico e devem ser adaptadas à legislação e às políticas aplicáveis antes de uso real.

## Privacidade

A edição pública usa colaboradores sintéticos e não contém escalas de produção, bancos corporativos, credenciais, tokens ou caminhos privados de integração.

**Baseline: 2.7.4.**

---

Desenvolvido por **Eduardo Lima**.
