## AAT Multiroom Digital

Integração para Home Assistant do sistema de áudio multiroom **AAT Digital
Matrix Amplifiers** (linhas PMA / PMRH / PMR). Comunicação via TCP/IP na rede
local — sem nuvem, sem latência.

Fork de [lcglustosa/aat-multiroom-ha](https://github.com/lcglustosa/aat-multiroom-ha)
com reconexão robusta, tratamento de erros do equipamento, mute reativado,
compatibilidade HomeKit opt-in e detecção automática de zonas pelo modelo.

---

### Funcionalidades

**Por zona (`media_player`):** liga/desliga (stand-by), volume 0–87, mute,
seleção de entrada. **Configuração:** graves, agudos, balanço, ganho de pré-amp.
**Dispositivo:** master power, ligar/desligar/mutar tudo, reiniciar.

---

### Configuração

1. Informe o **IP** e a **porta TCP** (5000 padrão; 1024 se quiser deixar a 5000
   para o app oficial).
2. Zonas e entradas são **detectadas automaticamente** pelo modelo.
3. Dê nomes amigáveis às zonas e entradas.
4. (Opcional) ligue **Compatibilidade HomeKit** para o slider de volume no app Casa.

---

### Compatibilidade

PMA-1/2, PMRH-2/4/6, PMR-4 a PMR-13. Firmware **V1.12+** recomendado. Testado no
PMR-4, revisado para o PMR-7. Nos modelos com streamer (PMR-9..13) esta
integração cobre a parte de zonas — use a integração nativa **`linkplay`** para o
streamer embutido.
