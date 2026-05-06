const express = require('express');
const axios = require('axios');
const https = require('https');
const fs = require('fs');
const path = require('path');
const cors = require('cors');

const app = express();
app.use(express.json());
app.use(cors());
app.use(express.static('public'));

// Credenciais fornecidas pelo usuário
const CLIENT_ID = '96b32874-da09-418e-bd03-8e59c7aa953e';
const CLIENT_SECRET = '2832080f-c925-4e27-a819-d03f6b6fd955';
const KEY_PATH = path.join(__dirname, 'Sandbox_InterAPI_Chave.key');

// IMPORTANTE: Para o mTLS funcionar com o Banco Inter, é necessário também o arquivo .crt
// Como foi enviado apenas o .key, o script procurará um .crt com o nome abaixo.
const CERT_PATH = path.join(__dirname, 'Sandbox_InterAPI_Certificado.crt'); 

let httpsAgent;

try {
    httpsAgent = new https.Agent({
        cert: fs.existsSync(CERT_PATH) ? fs.readFileSync(CERT_PATH) : '',
        key: fs.existsSync(KEY_PATH) ? fs.readFileSync(KEY_PATH) : '',
        rejectUnauthorized: true // Vamos testar com true
    });
} catch (error) {
    console.warn("Aviso: Falha ao carregar certificados mTLS.");
}

app.post('/api/boleto', async (req, res) => {
    try {
        const { value, cpfCnpj, name, email, zipCode, number, street, city, state, neighborhood } = req.body;

        if (!fs.existsSync(CERT_PATH)) {
            return res.status(500).json({ 
                error: "Arquivo de certificado (.crt) não encontrado.",
                message: "A API do Banco Inter exige mTLS. Você deve colocar o arquivo 'Sandbox_InterAPI_Certificado.crt' na mesma pasta do servidor."
            });
        }

        // 1. Obter o Token OAuth2
        const tokenParams = new URLSearchParams();
        tokenParams.append('client_id', CLIENT_ID);
        tokenParams.append('client_secret', CLIENT_SECRET);
        tokenParams.append('scope', 'boleto-cobranca.read boleto-cobranca.write');
        tokenParams.append('grant_type', 'client_credentials');

        const tokenResponse = await axios.post(
            'https://cdpj-sandbox.partners.uatinter.co/oauth/v2/token',
            tokenParams.toString(),
            {
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                httpsAgent
            }
        );

        const accessToken = tokenResponse.data.access_token;

        // 2. Criar o Boleto
        const boletoPayload = {
            "seuNumero": `T-${Date.now().toString().slice(-10)}`,
            "valorNominal": parseFloat(value),
            "dataVencimento": new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0], // Daqui a 7 dias
            "numDiasAgenda": 30,
            "pagador": {
                "cpfCnpj": cpfCnpj.replace(/\D/g, ''),
                "tipoPessoa": cpfCnpj.replace(/\D/g, '').length === 11 ? "FISICA" : "JURIDICA",
                "nome": name,
                "endereco": street,
                "numero": number,
                "bairro": neighborhood,
                "cidade": city,
                "uf": state,
                "cep": zipCode.replace(/\D/g, ''),
                "email": email,
                "ddd": "11",
                "telefone": "999999999"
            },
            "mensagem": {
                "linha1": "Boleto de teste gerado pelo sistema",
                "linha2": "Sandbox Inter API"
            }
        };

        const boletoResponse = await axios.post(
            'https://cdpj-sandbox.partners.uatinter.co/cobranca/v3/cobrancas',
            boletoPayload,
            {
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                    'Content-Type': 'application/json',
                    'x-conta-corrente': '123456789'
                },
                httpsAgent
            }
        );

        const codigoSolicitacao = boletoResponse.data.codigoSolicitacao;
        let boletoFinal = boletoResponse.data;

        // Como a API V3 é assíncrona, vamos esperar 1.5 segundo e buscar os dados completos
        if (codigoSolicitacao) {
            await new Promise(resolve => setTimeout(resolve, 1500));
            try {
                const getResponse = await axios.get(
                    `https://cdpj-sandbox.partners.uatinter.co/cobranca/v3/cobrancas/${codigoSolicitacao}`,
                    {
                        headers: {
                            'Authorization': `Bearer ${accessToken}`,
                            'x-conta-corrente': '123456789'
                        },
                        httpsAgent
                    }
                );
                
                // Formatar para exibição igual no frontend
                boletoFinal = getResponse.data;
                boletoFinal.nossoNumero = boletoFinal.cobranca?.nossoNumero || 'N/A';
                boletoFinal.linhaDigitavel = boletoFinal.boleto?.linhaDigitavel || 'N/A';
                boletoFinal.codigoBarras = boletoFinal.boleto?.codigoBarras || 'N/A';

                // Tentar buscar o PDF do boleto
                try {
                    const pdfResponse = await axios.get(
                        `https://cdpj-sandbox.partners.uatinter.co/cobranca/v3/cobrancas/${codigoSolicitacao}/pdf`,
                        {
                            headers: {
                                'Authorization': `Bearer ${accessToken}`,
                                'x-conta-corrente': '123456789'
                            },
                            httpsAgent
                        }
                    );
                    if (pdfResponse.data && pdfResponse.data.pdf) {
                        boletoFinal.pdfBase64 = pdfResponse.data.pdf;
                    }
                } catch (pdfErr) {
                    console.warn('Erro ao buscar PDF do boleto:', pdfErr.message);
                }

            } catch (err) {
                console.warn('Erro ao buscar detalhes da cobranca assincrona:', err.message);
            }
        }

        res.json({ success: true, data: boletoFinal });
    } catch (error) {
        console.error('Erro na requisição da API:', error.response?.data || error.message);
        res.status(500).json({ 
            success: false, 
            error: error.response?.data || error.message 
        });
    }
});

const PORT = 3000;
app.listen(PORT, () => {
    console.log(`\n======================================================`);
    console.log(`🚀 Servidor de Teste rodando em http://localhost:${PORT}`);
    console.log(`======================================================\n`);
    if (!fs.existsSync(CERT_PATH)) {
        console.log(`\x1b[31m[ATENÇÃO] ERRO DE CERTIFICADO FALTANTE\x1b[0m`);
        console.log(`O arquivo de certificado público não foi encontrado em:`);
        console.log(`-> ${CERT_PATH}`);
        console.log(`A API do Banco Inter utiliza mTLS, o que exige a chave (.key) E o certificado (.crt).`);
        console.log(`Por favor, coloque o seu arquivo de certificado com o nome 'Sandbox_InterAPI_Certificado.crt' na pasta do projeto.\n`);
    } else {
        console.log(`\x1b[32m[OK] Certificado e chave encontrados!\x1b[0m\n`);
    }
});
