# AAT Multiroom Digital — integração para Home Assistant

Integração custom (não-oficial) que conecta os amplificadores **AAT Digital
Matrix** (linhas PMA / PMRH / PMR) ao **Home Assistant** via TCP na rede local —
sem nuvem, sem latência. Cada zona vira um `media_player`; por extensão funciona
com **Alexa** e **Apple Home** quando você usa o HomeKit Bridge ou o Nabu Casa.

> **Fork** de [lcglustosa/aat-multiroom-ha](https://github.com/lcglustosa/aat-multiroom-ha)
> (MIT, Leandro Lustosa), com correções de robustez e revisado contra a *AAT
> Digital Matrix Amplifiers API Rev.12* (firmware V3.08+). Ver `NOTICE.md` para
> a lista de mudanças.

---

## O que cada zona expõe

**`media_player.<zona>`** (controle principal):
- Liga / desliga (entra/sai de stand-by por zona — `ZSTDBYOFF` / `ZSTDBYON`)
- Volume contínuo (0–87 dB) + volume up/down
- **Mute** (`MUTEON` / `MUTEOFF`)
- Seleção de fonte (entradas analógicas e digitais, com nomes amigáveis)

**Controles por zona** (na seção *Configuração* do dispositivo):
- Graves e Agudos (`number`, 0–14, centro 7)
- Balanço (`number`, 0–20, centro 10)
- Ganho de pré-amp (`number`, 0–7)

**Nível do aparelho:**
- `switch` Power (master `PWRON` / `PWROFF`)
- `switch` Mute All (`MUTEALL` / `UNMUTEALL`)
- `button` Ligar/Desligar todas as zonas (`ZTONALL` / `ZSTDBYALL`), Mutar/Desmutar tudo, Reiniciar

---

## Requisitos

- AAT da linha PMA/PMRH/PMR com firmware **≥ V1.12** (o que tem porta TCP).
  Testado no PMR-4; revisado para o PMR-7.
- Home Assistant **≥ 2024.4**.
- AAT acessível via rede do HA (mesma LAN ou rota TCP).
- **IP fixo no AAT** (reserva DHCP recomendada).

---

## Instalação

### Via HACS
1. Adicione este repositório como **repositório customizado** (tipo: Integration).
2. Instale **AAT Multiroom Digital** e reinicie o HA.

### Manual
Copie `custom_components/aat_multiroom/` para o diretório `custom_components/` do
seu HA e reinicie.

---

## Configuração

1. **Configurações → Dispositivos e Serviços → Adicionar integração → AAT Multiroom Digital**.
2. Informe:
   - **IP** do amplificador.
   - **Porta TCP**: `5000` (padrão). Use `1024` (porta secundária configurável)
     se quiser deixar a 5000 livre para o app oficial da AAT.
3. O número de **zonas e entradas é detectado automaticamente** a partir do
   `MODEL` do aparelho (PMR-7 → 6 zonas / 6 entradas). Você não precisa saber a
   topologia do seu modelo.
4. Dê **nomes amigáveis** às zonas e entradas (ex.: "Sala", "Cozinha", "Spotify",
   "TV"). Deixe uma entrada em branco para ocultá-la.
5. (Opcional) marque **Compatibilidade HomeKit** — ver seção Apple Home abaixo.

O dispositivo aparece como **AAT `<modelo>`** com um `media_player` por zona.
Para editar nomes/opção depois: **… → AAT Multiroom Digital → Configurar**.

Se o modelo não for reconhecido, use **Reconfigurar** para ajustar IP/porta e o
número de zonas manualmente.

---

## Alexa (via Nabu Casa)

1. No HA: **Configurações → Home Assistant Cloud**, ative Alexa e exponha os
   `media_player` de cada zona.
2. No app Alexa: **Dispositivos → +** → procurar novos dispositivos. As zonas
   aparecem como alto-falantes; atribua cada uma a um Cômodo.

| Comando de voz | Efeito |
| --- | --- |
| "Alexa, ligar a Sala" | `ZSTDBYOFF` na Sala |
| "Alexa, volume do Quarto em 30%" | `VOLSET` ≈ 26/87 |
| "Alexa, mutar a Varanda" | `MUTEON` na Varanda |

Troca de fonte por voz é limitada na Alexa; se não funcionar direto, crie uma
Rotina que chame `media_player.select_source`.

---

## Apple Home (HomeKit Bridge)

Por padrão cada zona usa `device_class = SPEAKER` (semântica correta) e tem mute
de verdade. **Se você usa o app Casa**, o HomeKit Bridge do HA renderiza um
`SPEAKER` como um botão on/off simples, **sem slider de volume**. Para ter o
slider, ligue a opção **Compatibilidade HomeKit** na configuração da integração:

- as zonas passam a expor também uma entidade **`light.<zona> (volume)`** cujo
  brilho é o volume — o único jeito de ter slider de volume na Casa;
- o `media_player` passa a usar `device_class = TV`.

No `homekit:` (ou na config da HomeKit Bridge) inclua as `light.*` das zonas:

```yaml
homekit:
  - name: AAT Multiroom
    filter:
      include_entities:
        - light.aat_pmr7_sala_volume
        - light.aat_pmr7_cozinha_volume
        - switch.aat_pmr7_power
```

Deixe a opção **desligada** se você não usa HomeKit — aí você fica só com os
`media_player` (SPEAKER + mute), mais limpos.

---

## Como funciona por dentro

- **Protocolo**: TCP, mensagens ASCII `[t<seq> <CMD> <par...>]`. Ver `aat_protocol.py`.
- **Polling**: a cada 20 s o coordinator manda `GETALL` (tudo de uma vez) +
  `ZSTDBYGET` por zona (o GETALL não traz stand-by), só quando o aparelho está ligado.
- **Conexão**: uma `AatClient` compartilhada por todas as entidades, com lock
  serializando request→resposta e casamento de sequencial. Se o AAT resetar a
  conexão ociosa (`TCPTIMEOUT`), o próximo comando **reconecta e refaz sozinho**.
- **Erros do equipamento** (códigos 7/8/17/18) são detectados e mostrados na UI
  como `AatCommandError` em vez de falharem em silêncio.

| HA `media_player` | Comando AAT |
| --- | --- |
| `turn_on` | `ZSTDBYOFF <zona>` (+ `PWRON` se o aparelho estiver desligado) |
| `turn_off` | `ZSTDBYON <zona>` |
| `volume_set` (0.0–1.0) | `VOLSET <zona> <0–87>` |
| `volume_up` / `down` | `VOL+` / `VOL-` |
| `volume_mute` | `MUTEON` / `MUTEOFF` |
| `select_source` | `INPSET <zona> <1–8>` |

---

## Compatibilidade

| Modelo | Entradas | Zonas |  | Modelo | Entradas | Zonas |
|---|---|---|---|---|---|---|
| PMA-1 | 4 | 4 | | PMR-7 | 6 | 6 |
| PMA-2 | 4 | 6 | | PMR-8 | 5 | 2 |
| PMRH-2 | 6 | 2 | | PMR-9¹ | 7 | 4 |
| PMRH-4 | 6 | 4 | | PMR-10¹ | 7 | 6 |
| PMRH-6 | 6 | 6 | | PMR-11¹ | 8 | 4 |
| PMR-4 | 4 | 4 | | PMR-12¹ | 8 | 6 |
| PMR-5 | 4 | 6 | | PMR-13¹ | 6 | 2 |
| PMR-6 | 6 | 4 | | | | |

¹ Modelos com streamer. Esta integração controla a **parte matriz** (zonas). O
streamer embutido é hardware LinkPlay/WiiMu — use a integração nativa
**`linkplay`** do HA para play/pause/streaming.

---

## Limitações conhecidas

- **Sem push**: mudanças feitas pelo controle remoto/painel/app aparecem no
  próximo poll (≤ 20 s). O parser já reconhece as mensagens não solicitadas
  `[n...]`, mas elas ainda não alimentam o estado (melhoria futura → `local_push`).
- **MONO / STEREO / BRIDGE** e o menu de instalação do AAT não são acessíveis por
  automação (restrição do próprio equipamento) — configure pelo painel frontal.
- Detecção de erro dos códigos 7/8/17/18 é *best-effort* pela ambiguidade de
  enquadramento do protocolo; validar contra o PMR-7 real.

---

## Testes

```
python3 -m pytest tests/ -v
```

Cobrem encoder/parser, `GETALL` (exemplo do datasheet PMR-7), detecção de erro,
reconexão com retry e a derivação de topologia pelo MODEL.

---

## Licença

MIT — ver `LICENSE` (© Leandro Lustosa) e `NOTICE.md`. Não é endossado nem
suportado oficialmente pela Advanced Audio Technologies.
