# Deep_Learning

See detailed project description here.
Supervised by Alexander Neergaard Zahid &lt;aneol@dtu.dk> and Morten Mørup &lt;mmor@dtu.dk>.

# Object detection models for sleep micro-event analysis:

Project for course 02456 Deep Learning
January 2023

## Authors

 - Siham Kida (s210154)
 - Jedrzej Konrad Kolbert (s184361)
 - Matteo Sabadin (s212980)
 - Muse Ali (s194615)

## Structure of files

In this folder you can find the following files:
 - The script "main" to train the model for the first approach.
 - The script "main2" to train the model for the second approach.
 - The script "Visualization" is to show the results of the models used.
 - The pdf "poster" that is the poster of this project.

## Training
To train model for 31 epochs run with 4 encoder layers 4 decoder layers and 20 queries prediction:
```python
python main.py --enc_layers 4 --dec_layers 4 --dim_feedforward 1024 --epochs 31 --num_workers 8 --num_queries 20
```

## Visualization
To visualize the model outputs a "checkpoint.pth" file is needed. The example visualization command is:
```python
python Visualization.py --resume ../checkpoint.pth --enc_layers 4 --dec_layers 4 --dim_feedforward 1024 --overfit --num_workers 8 --num_queries 20
```

## Log file
Log file 'log.txt' allows for the monitoring of the loss function change over training epochs:
```python
from util.plot_utils import plot_logs
from pathlib import Path
pth = "file_path"
plot_logs([Path(pth)], fields=['loss'],log_name='log.txt')
```
