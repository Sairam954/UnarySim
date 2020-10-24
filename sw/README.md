# Overview

This directory contains the components to simulate unary computing in a cycle-accurate manner. 
The components included in UnarySim belong to three categories, including 
1. **Stream Manipulation**
2. **Computing Kernel**
3. **Performance Metric**

Among those, components in **Stream Manipulation** and **Unary Computing Kernel** can pysically exist in real hardware, while those from **Performance Metric** is usually for performance analysis.

## Prerequisite
1. PyTorch version >= 1.0
2. Python version >= 3.6
3. [pylfsr](https://github.com/Nikeshbajaj/Linear_Feedback_Shift_Register)

## Data Representation
UnarySim has five categories of data, with each having default data type as _**'torch.float'**_ in PyTorch.

1. **Source Data**: 
The input source data in unary computing need to be ranging from _0_ to _1_ in **unipolar** format, or from _-1_ to _1_ in **bipolar** format. 
The input source data (_source_) is scaled to a certain range (as in _unipolar/bipolar_ format) from the raw data (_raw_) with respect to its maximum.
More specifically, such a relationship is formulated as _source = raw / max(raw)_.

2. **Random Number**: 
The random numbers (_rand_) are to be compared with the source data in order to generate the data streams. To notice, source data is in _unipolar/bipolar_ format, while random numbers are integers. 
To compare them, source data requires to scale up by the _bitwidth_ of random numbers. 
At each cycle, if _round(source * 2^bitwidth) > rand_, a bit of logic 1 in the stream will be generated; otherwise, a bit of logic 0 will be generated.

3. **Stream**: 
At each cycle, the data in the streams physically flow through cascaded logic kernels, and they count for most of the memory space during simulation.

4. **Buffer**: 
Inside each logic kernel, there may exist buffers, like counters or shift registers, to compute future data by monitoring the past data streams. 

5. **Metric Variable**: 
Those are variables to compute specially designed performance metrics.

## Directory Hierarchy
This directory contains four subdirectories, including _'stream'_, _'kernel'_,  _'metric'_ and _'test'_, covering three components mentioned above.

### _'stream'_ subdirectory
This directory contains the components for **Stream Manipulation**, which manipulate the data streams for high performance and accuracy.

| Name                 | Date         | Encoding | Polarity | Reference | Status                 |
| -------------------- | ------------ | -------- | -------- | --------- | ---------------------- |
| BSGen                | Seq 07, 2019 | Both     | Both     | [1]       | <ul><li>[x] </li></ul> |
| BSGenMulti           | Nov 11, 2019 | Both     | Both     | [1]       | <ul><li>[x] </li></ul> |
| RawScale             | Dec 07, 2019 | Both     | Either   | NA        | <ul><li>[x] </li></ul> |
| RNG                  | Seq 07, 2019 | Both     | Both     | [2]       | <ul><li>[x] </li></ul> |
| RNGMulti             | Nov 11, 2019 | Both     | Both     | [2]       | <ul><li>[x] </li></ul> |
| SourceGen            | Seq 07, 2019 | Both     | Either   | [1]       | <ul><li>[x] </li></ul> |
| Decorr               |              | Both     | Both     | [3]       | <ul><li>[ ] </li></ul> |
| DeSync               |              | RC       | Both     | [3]       | <ul><li>[ ] </li></ul> |
| SkewedSync           | Seq 07, 2019 | Both     | Both     | [4]       | <ul><li>[x] </li></ul> |
| Sync                 |              | Both     | Both     | [3]       | <ul><li>[ ] </li></ul> |
| Bi2Uni               | Mar 31, 2020 | RC       | Bi       | [10]      | <ul><li>[x] </li></ul> |
| Uni2Bi               | Mar 31, 2020 | RC       | Uni      | [10]      | <ul><li>[x] </li></ul> |


### _'kernel'_ subdirectory
This directory contains the components for **Unary Computing Kernel**, which take data streams as inputs and perform actual unary computation. The supported kernels are listed as follows.
The components currently supported or to be implemented are listed in the table below.

| Name                 | Date         | Encoding | Polarity | Reference | Status                 |
| -------------------- | ------------ | -------- | -------- | --------- | ---------------------- |
| UnaryAbs             | Mar 25, 2020 | RC       | Bi       | NA        | <ul><li>[x] </li></ul> |
| UnarySign            | Mar 31, 2020 | RC       | Bi       | NA        | <ul><li>[x] </li></ul> |
| UnaryAdd             | Oct 10, 2019 | Both     | Either   | [5]       | <ul><li>[x] </li></ul> |
| UnaryMul             | Nov 05, 2019 | Both     | Either   | [5]       | <ul><li>[x] </li></ul> |
| UnaryLinear          | Seq 27, 2019 | Both     | Either   | [5]       | <ul><li>[x] </li></ul> |
| UnaryReLU            | Nov 23, 2019 | Either   | Either   | [5]       | <ul><li>[x] </li></ul> |
| CORDIV_kernel        | Mar 08, 2020 | RC       | Uni      | [4]       | <ul><li>[x] </li></ul> |
| UnaryDiv             | Apr 01, 2020 | RC       | Either   | [4]       | <ul><li>[x] </li></ul> |
| UnarySqrt            | Apr 02, 2020 | RC       | Either   | [4]       | <ul><li>[x] </li></ul> |
| GainesAdd            | Mar 02, 2020 | Both     | Either   | [1]       | <ul><li>[x] </li></ul> |
| GainesMul            | Dec 06, 2019 | RC       | Either   | [1]       | <ul><li>[x] </li></ul> |
| GainesLinear         | Nov 25, 2019 | RC       | Either   | [1]       | <ul><li>[x] </li></ul> |
| GainesDiv            | Mar 08, 2020 | RC       | Either   | [1]       | <ul><li>[x] </li></ul> |
| GainesSqrt           | Mar 24, 2020 | RC       | Either   | [1]       | <ul><li>[x] </li></ul> |
| nn_utils             | Nov 25, 2019 | NA       | NA       | NA        | <ul><li>[x] </li></ul> |
| JKFF                 | Apr 01, 2020 | NA       | NA       | NA        | <ul><li>[x] </li></ul> |
| ShiftReg             | Dec 06, 2019 | NA       | NA       | NA        | <ul><li>[x] </li></ul> |
| comparison           |              |          |          |           | <ul><li>[ ] </li></ul> |
| conv                 |              |          |          |           | <ul><li>[ ] </li></ul> |
| exponentiation       |              |          |          |           | <ul><li>[ ] </li></ul> |
| max                  |              |          |          |           | <ul><li>[ ] </li></ul> |
| min                  |              |          |          |           | <ul><li>[ ] </li></ul> |
| pool                 |              |          |          |           | <ul><li>[ ] </li></ul> |


### _'metric'_ subdirectory
This directory contains the components for **Performance Metric**, which take bit streams as input and calculate certain performance metrics.
The components currently supported or to be implemented are listed in the table below.

| Name                 | Date         | Encoding | Polarity | Reference | Status                 |
| -------------------- | ------------ | -------- | -------- | --------- | ---------------------- |
| Correlation          | Seq 07, 2019 | Both     | Both     | [6]       | <ul><li>[x] </li></ul> |
| ProgressiveError     | Seq 07, 2019 | Both     | Either   | [7]       | <ul><li>[x] </li></ul> |
| Stability            | Dec 27, 2019 | Both     | Either   | [5]       | <ul><li>[x] </li></ul> |
| NormStability        | Dec 18, 2019 | Both     | Either   | [9]       | <ul><li>[x] </li></ul> |
| NSBuilder            | Mar 31, 2020 | Both     | Either   | [9]       | <ul><li>[x] </li></ul> |


### _'test'_ subdirectory
This directory contains simple testing examples for above components, which are integrated with Jupyter-notebook.


## Reference
[1] B.R. Gaines, "Stochastic computing systems," in _Advances in Information Systems Science_ 1969.  
[2] S. Liu and J. Han, "Energy efficient stochastic computing with Sobol sequences," in _DATE_ 2017.  
[3] V. T. Lee, A. Alaghi and L. Ceze, "Correlation manipulating circuits for stochastic computing," in _DATE_ 2018.  
[4] D. Wu and J. S. Miguel, "In-Stream Stochastic Division and Square Root via Correlation," in _DAC_ 2019.  
[5] D. Wu, J. Li, R. Yin, H. Hsiao, Y. Kim and J. San Miguel, "uGEMM: Unary Computing Architecture for GEMM Applications," in _ISCA_ 2020.  
[6] A. Alaghi and J. P. Hayes, "Exploiting correlation in stochastic circuit design," in _ICCD_ 2013.  
[7] A. Alaghi and J. P. Hayes, "Fast and accurate computation using stochastic circuits," in _DATE_ 2014.  
[8] P. Li and D. J. Lilja, W. Qian, M. D. Riedel and K. Bazargan, "Logical Computation on Stochastic Bit Streams with Linear Finite-State Machines," in _IEEE Transactions On Computers_, 2014.  
[9] D. Wu, R. Yin and J. San Miguel, "Normalized Stability: A Cross-Level Design Metric for Early Termination in Stochastic Computing", in _ASP-DAC_ 2021.  
[10] D. Wu, R. Yin and J. San Miguel, "In-Stream Correlation-Based Division and Bit-Inserting Square Root in Stochastic Computing", under review.