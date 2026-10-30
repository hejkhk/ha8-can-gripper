/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
/* 协议只发送整数，避免使用 printf 浮点格式和额外堆内存 */
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define SAMPLE_PERIOD_MS        10U      /* 100 Hz */
#define ADC_AVG_COUNT           16U      /* 16次 ADC 平均 */
#define ADC_REFERENCE_MV        3300U    /* VDDA 标称值；精度测量需实测 */
#define FILTER_SHIFT           2U       /* EMA 的 alpha=1/4 */
#define UART_TIMEOUT_MS        15U
#define STATUS_ADC_ERROR       0x01U
#define STATUS_HIGH_RAIL       0x02U
#define STATUS_CAL_FAILED      0x04U
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
ADC_HandleTypeDef hadc1;

UART_HandleTypeDef huart1;

/* USER CODE BEGIN PV */
static uint32_t s_sequence = 0U;
static uint32_t s_next_sample_ms = 0U;
static int32_t s_filter_q8 = 0;
static uint8_t s_filter_ready = 0U;
static uint8_t s_adc_calibrated = 0U;
static uint16_t s_last_adc = 0U;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_ADC1_Init(void);
static void MX_USART1_UART_Init(void);
/* USER CODE BEGIN PFP */
static uint8_t Pressure_ReadAverage(uint16_t *adc_out);
static uint16_t Pressure_Filter(uint16_t adc_in);
static char *Protocol_AppendU32(char *cursor, uint32_t value);
static void Protocol_SendFrame(uint16_t adc, uint8_t status, uint32_t now_ms);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
/**
 * @brief  读取 PA1 上的电压，取 ADC_AVG_COUNT 次平均值。
 *         成功返回1；发生任何 ADC 错误时返回0，不把失败读数当0V。
 */
static uint8_t Pressure_ReadAverage(uint16_t *adc_out)
{
  uint32_t sum = 0U;
  uint32_t i;
  for (i = 0U; i < ADC_AVG_COUNT; ++i)
  {
    if (HAL_ADC_Start(&hadc1) != HAL_OK)
    {
      (void)HAL_ADC_Stop(&hadc1);
      return 0U;
    }
    if (HAL_ADC_PollForConversion(&hadc1, 5U) != HAL_OK)
    {
      (void)HAL_ADC_Stop(&hadc1);
      return 0U;
    }
    sum += HAL_ADC_GetValue(&hadc1);
    if (HAL_ADC_Stop(&hadc1) != HAL_OK)
    {
      return 0U;
    }
  }
  *adc_out = (uint16_t)((sum + ADC_AVG_COUNT / 2U) / ADC_AVG_COUNT);
  return 1U;
}

/**
 * @brief  一阶指数滤波。Q8 定点实现，避免浮点与累积舍入误差。
 *         初始样本直接作为滤波初值，防止开机数值从0缓慢爬升。
 */
static uint16_t Pressure_Filter(uint16_t adc_in)
{
  int32_t target_q8 = (int32_t)adc_in * 256;
  if (s_filter_ready == 0U)
  {
    s_filter_q8 = target_q8;
    s_filter_ready = 1U;
  }
  else
  {
    s_filter_q8 += (target_q8 - s_filter_q8) / (1 << FILTER_SHIFT);
  }
  return (uint16_t)((s_filter_q8 + 128) / 256);
}

/** @brief 将非负整数追加到字符串，返回新的尾指针。 */
static char *Protocol_AppendU32(char *cursor, uint32_t value)
{
  char digits[10];
  uint8_t size = 0U;
  do
  {
    digits[size++] = (char)('0' + (value % 10U));
    value /= 10U;
  } while ((value != 0U) && (size < sizeof(digits)));
  while (size != 0U)
  {
    *cursor++ = digits[--size];
  }
  return cursor;
}

/**
 * @brief  协议：P,seq,ms,adc,mv,flags\r\n
 *         状态位：bit0 ADC失败；bit1 高端饱和；bit2 ADC上电校准失败。
 *         无压力电压接近零是正常情况，不把低端电压当断线。
 */
static void Protocol_SendFrame(uint16_t adc, uint8_t status, uint32_t now_ms)
{
  char message[64];
  char *cursor = message;
  uint32_t mv = ((uint32_t)adc * ADC_REFERENCE_MV + 2047U) / 4095U;
  *cursor++ = 'P';
  *cursor++ = ',';
  cursor = Protocol_AppendU32(cursor, s_sequence++);
  *cursor++ = ',';
  cursor = Protocol_AppendU32(cursor, now_ms);
  *cursor++ = ',';
  cursor = Protocol_AppendU32(cursor, adc);
  *cursor++ = ',';
  cursor = Protocol_AppendU32(cursor, mv);
  *cursor++ = ',';
  cursor = Protocol_AppendU32(cursor, status);
  *cursor++ = '\r';
  *cursor++ = '\n';
  (void)HAL_UART_Transmit(&huart1, (uint8_t *)message,
                           (uint16_t)(cursor - message), UART_TIMEOUT_MS);
}
/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_ADC1_Init();
  MX_USART1_UART_Init();
  /* USER CODE BEGIN 2 */
  /* 校准失败不伪装正常，状态字 bit2 提示上位机 */
  s_adc_calibrated = (HAL_ADCEx_Calibration_Start(&hadc1) == HAL_OK) ? 1U : 0U;
  s_next_sample_ms = HAL_GetTick();
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    uint32_t now_ms = HAL_GetTick();
    if ((int32_t)(now_ms - s_next_sample_ms) >= 0)
    {
      uint16_t average;
      uint8_t flags = (s_adc_calibrated != 0U) ? 0U : STATUS_CAL_FAILED;
      if (Pressure_ReadAverage(&average) != 0U)
      {
        s_last_adc = Pressure_Filter(average);
      }
      else
      {
        flags |= STATUS_ADC_ERROR;
      }
      if (s_last_adc >= 4090U)
      {
        flags |= STATUS_HIGH_RAIL;
      }
      Protocol_SendFrame(s_last_adc, flags, now_ms);
      /* 若发生延迟，丢弃过期周期，不连续突发发送多帧 */
      s_next_sample_ms += SAMPLE_PERIOD_MS;
      if ((int32_t)(HAL_GetTick() - s_next_sample_ms) >= 0)
      {
        s_next_sample_ms = HAL_GetTick() + SAMPLE_PERIOD_MS;
      }
    }
    else
    {
      HAL_Delay(1U);
    }
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};
  RCC_PeriphCLKInitTypeDef PeriphClkInit = {0};

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0) != HAL_OK)
  {
    Error_Handler();
  }
  PeriphClkInit.PeriphClockSelection = RCC_PERIPHCLK_ADC;
  PeriphClkInit.AdcClockSelection = RCC_ADCPCLK2_DIV2;
  if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInit) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief ADC1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_ADC1_Init(void)
{

  /* USER CODE BEGIN ADC1_Init 0 */

  /* USER CODE END ADC1_Init 0 */

  ADC_ChannelConfTypeDef sConfig = {0};

  /* USER CODE BEGIN ADC1_Init 1 */

  /* USER CODE END ADC1_Init 1 */

  /** Common config
  */
  hadc1.Instance = ADC1;
  hadc1.Init.ScanConvMode = ADC_SCAN_DISABLE;
  hadc1.Init.ContinuousConvMode = DISABLE;
  hadc1.Init.DiscontinuousConvMode = DISABLE;
  hadc1.Init.ExternalTrigConv = ADC_SOFTWARE_START;
  hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
  hadc1.Init.NbrOfConversion = 1;
  if (HAL_ADC_Init(&hadc1) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure Regular Channel
  */
  sConfig.Channel = ADC_CHANNEL_1;
  sConfig.Rank = ADC_REGULAR_RANK_1;
  sConfig.SamplingTime = ADC_SAMPLETIME_239CYCLES_5;
  if (HAL_ADC_ConfigChannel(&hadc1, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN ADC1_Init 2 */

  /* USER CODE END ADC1_Init 2 */

}

/**
  * @brief USART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART1_UART_Init(void)
{

  /* USER CODE BEGIN USART1_Init 0 */

  /* USER CODE END USART1_Init 0 */

  /* USER CODE BEGIN USART1_Init 1 */

  /* USER CODE END USART1_Init 1 */
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 115200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART1_Init 2 */

  /* USER CODE END USART1_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOA_CLK_ENABLE();

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
